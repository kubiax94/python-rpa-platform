from __future__ import annotations

import asyncio
import json
import logging
import shutil
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any

from vm_agent_server.src.agent_registry_db import AgentRegistryDB, hash_token

logger = logging.getLogger(__name__)


class DeploymentService:
    def __init__(self, registry_db: AgentRegistryDB, repo_root: Path):
        self._registry_db = registry_db
        self._repo_root = repo_root
        self._artifacts_root = repo_root / "artifacts" / "deployments"
        self._tasks: dict[str, asyncio.Task] = {}

    async def prepare_deployment(
        self,
        *,
        agent_id: str,
        hostname: str,
        display_name: str,
        source_ref: str,
        requested_by: str,
        server_ws_url: str,
    ) -> dict[str, Any]:
        deployment_id = uuid.uuid4().hex
        bootstrap_token = uuid.uuid4().hex + uuid.uuid4().hex
        bootstrap_expires_at = int(time.time()) + 3600

        await self._registry_db.upsert_agent(
            agent_id,
            hostname=hostname,
            display_name=display_name,
            status="provisioning",
            connection_status="offline",
            last_deployment_id=deployment_id,
        )
        await self._registry_db.set_bootstrap_token(agent_id, hash_token(bootstrap_token), bootstrap_expires_at)
        await self._registry_db.create_deployment(deployment_id, agent_id, hostname, source_ref, requested_by)

        task = asyncio.create_task(
            self._run_prepare(
                deployment_id=deployment_id,
                agent_id=agent_id,
                hostname=hostname,
                display_name=display_name,
                source_ref=source_ref,
                server_ws_url=server_ws_url,
                bootstrap_token=bootstrap_token,
                bootstrap_expires_at=bootstrap_expires_at,
            )
        )
        self._tasks[deployment_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(deployment_id, None))

        deployment = await self._registry_db.get_deployment(deployment_id)
        return deployment or {"id": deployment_id, "status": "queued"}

    async def _run_prepare(
        self,
        *,
        deployment_id: str,
        agent_id: str,
        hostname: str,
        display_name: str,
        source_ref: str,
        server_ws_url: str,
        bootstrap_token: str,
        bootstrap_expires_at: int,
    ):
        build_log_parts: list[str] = []
        artifact_root = self._artifacts_root / deployment_id
        worktree_dir = artifact_root / "_worktree"
        package_dir = artifact_root / "package"
        started_at = int(time.time())

        await self._registry_db.update_deployment(deployment_id, status="building", started_at=started_at)

        try:
            artifact_root.mkdir(parents=True, exist_ok=True)

            commit_sha = (await self._run_command(
                ["git", "rev-parse", source_ref],
                cwd=self._repo_root,
            )).strip()
            build_log_parts.append(f"Resolved {source_ref} -> {commit_sha}")

            if worktree_dir.exists():
                shutil.rmtree(worktree_dir, ignore_errors=True)

            await self._run_command(
                ["git", "worktree", "add", "--detach", str(worktree_dir), commit_sha],
                cwd=self._repo_root,
            )
            build_log_parts.append(f"Created worktree: {worktree_dir}")

            python_exe = self._repo_root / "env" / "Scripts" / "python.exe"
            if not python_exe.exists():
                raise RuntimeError(f"Python environment not found: {python_exe}")

            build_output = await self._run_command(
                [str(python_exe), "-m", "PyInstaller", "--clean", "agent_service.spec"],
                cwd=worktree_dir,
            )
            build_log_parts.append(build_output)

            built_exe = worktree_dir / "dist" / "agent_service.exe"
            if not built_exe.exists():
                raise RuntimeError(f"Build succeeded without expected artifact: {built_exe}")

            package_dir.mkdir(parents=True, exist_ok=True)
            artifact_exe = package_dir / "agent_service.exe"
            shutil.copy2(built_exe, artifact_exe)

            bootstrap_path = package_dir / "agent.bootstrap.json"
            bootstrap_payload = {
                "agent_id": agent_id,
                "hostname": hostname,
                "display_name": display_name,
                "server_url": server_ws_url,
                "bootstrap_token": bootstrap_token,
                "bootstrap_expires_at": bootstrap_expires_at,
                "deployment_id": deployment_id,
                "source_ref": source_ref,
                "commit_sha": commit_sha,
            }
            bootstrap_path.write_text(json.dumps(bootstrap_payload, indent=2), encoding="utf-8")

            install_script_path = package_dir / "install.ps1"
            install_script_path.write_text(self._build_install_script(), encoding="utf-8")

            manifest_path = package_dir / "deployment-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "deployment_id": deployment_id,
                        "agent_id": agent_id,
                        "hostname": hostname,
                        "source_ref": source_ref,
                        "commit_sha": commit_sha,
                        "artifact_exe": artifact_exe.name,
                        "bootstrap_file": bootstrap_path.name,
                        "install_script": install_script_path.name,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            completed_at = int(time.time())
            await self._registry_db.update_deployment(
                deployment_id,
                status="ready",
                commit_sha=commit_sha,
                artifact_dir=str(package_dir),
                artifact_exe_path=str(artifact_exe),
                bootstrap_path=str(bootstrap_path),
                install_script_path=str(install_script_path),
                build_log="\n\n".join(build_log_parts),
                completed_at=completed_at,
            )
            await self._registry_db.upsert_agent(
                agent_id,
                hostname=hostname,
                display_name=display_name,
                status="ready_for_install",
                last_deployment_id=deployment_id,
                current_version=commit_sha[:12],
            )
        except Exception as exc:
            completed_at = int(time.time())
            build_log_parts.append(f"ERROR: {exc}")
            await self._registry_db.update_deployment(
                deployment_id,
                status="failed",
                error=str(exc),
                build_log="\n\n".join(build_log_parts),
                completed_at=completed_at,
            )
            await self._registry_db.upsert_agent(agent_id, hostname=hostname, display_name=display_name, status="deploy_failed")
        finally:
            if worktree_dir.exists():
                try:
                    await self._run_command(["git", "worktree", "remove", "--force", str(worktree_dir)], cwd=self._repo_root)
                except Exception as cleanup_error:
                    logger.warning("Failed to remove worktree %s: %s", worktree_dir, cleanup_error)
            try:
                await self._run_command(["git", "worktree", "prune"], cwd=self._repo_root)
            except Exception as prune_error:
                logger.debug("git worktree prune failed: %s", prune_error)

    async def _run_command(self, args: list[str], cwd: Path) -> str:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await process.communicate()
        output = stdout.decode("utf-8", errors="replace")
        if process.returncode != 0:
            raise RuntimeError(f"Command failed ({process.returncode}): {' '.join(args)}\n{output}")
        return output.strip()

    def _build_install_script(self) -> str:
        return textwrap.dedent(
            """
            param(
                [string]$InstallRoot = "C:\\agent\\MyOrciestra",
                [string]$ServiceName = "VmAgent"
            )

            $PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
            $ExePath = Join-Path $PackageRoot "agent_service.exe"
            $BootstrapPath = Join-Path $PackageRoot "agent.bootstrap.json"

            if (-not (Test-Path $ExePath)) {
                throw "agent_service.exe not found in package directory"
            }

            New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

            Copy-Item $ExePath (Join-Path $InstallRoot "agent_service.exe") -Force
            if (Test-Path $BootstrapPath) {
                Copy-Item $BootstrapPath (Join-Path $InstallRoot "agent.bootstrap.json") -Force
            }

            $InstalledExe = Join-Path $InstallRoot "agent_service.exe"

            if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
                Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
                & $InstalledExe remove 2>$null
                Start-Sleep -Seconds 1
            }

            & $InstalledExe install
            Start-Sleep -Seconds 1
            Start-Service -Name $ServiceName
            Get-Service -Name $ServiceName
            """
        ).strip() + "\n"