from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import shutil
import subprocess
import textwrap
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vm_agent_server.src.agent_registry_db import AgentRegistryDB, hash_token
from vm_agent_server.src.task_db import TaskDB
from vm_agent_server.src.task_dispatcher import TaskDispatchResult
from vm_agent_server.src.task_models import DeploymentTaskSpec, TaskBuilder

if TYPE_CHECKING:
    from vm_agent_server.src.task_service import TaskService

logger = logging.getLogger(__name__)


class DeploymentService:
    def __init__(self, registry_db: AgentRegistryDB, task_db: TaskDB, repo_root: Path):
        self._registry_db = registry_db
        self._task_db = task_db
        self._repo_root = repo_root
        self._artifacts_root = repo_root / "artifacts" / "deployments"
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_lock = asyncio.Lock()
        self._task_service: TaskService | None = None

    def set_task_service(self, task_service: "TaskService") -> None:
        self._task_service = task_service

    def get_default_repo_url(self) -> str:
        override = os.getenv("VM_AGENT_REPO_URL")
        if override:
            return override
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=self._repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def get_artifact_share_root(self) -> str:
        override = os.getenv("VM_AGENT_ARTIFACT_SHARE_ROOT")
        if override:
            return override
        return f"\\\\{socket.gethostname()}\\agent\\DevOPS\\artifacts\\deployments"

    def get_latest_installer_share_template(self) -> str:
        share_root = self.get_artifact_share_root()
        if share_root.endswith("\\deployments"):
            return share_root[: -len("\\deployments")] + "\\latest\\install-{deployment_id}.ps1"
        return share_root + "\\..\\latest\\install-{deployment_id}.ps1"

    async def get_prepare_config(self) -> dict[str, Any]:
        active = await self._registry_db.get_active_deployment()
        return {
            "default_repo_url": self.get_default_repo_url(),
            "default_source_ref": "main",
            "artifact_share_root": self.get_artifact_share_root(),
            "latest_installer_share_template": self.get_latest_installer_share_template(),
            "active_deployment": active,
        }

    async def prepare_deployment(
        self,
        *,
        agent_id: str,
        hostname: str,
        display_name: str,
        repo_url: str,
        source_ref: str,
        requested_by: str,
        server_ws_url: str,
    ) -> dict[str, Any]:
        async with self._active_lock:
            active_deployment = await self._registry_db.get_active_deployment()
            if active_deployment:
                raise RuntimeError(
                    f"Another deployment is already running: {active_deployment['id']} ({active_deployment['hostname']})"
                )

        deployment_id = uuid.uuid4().hex
        task_id = uuid.uuid4().hex
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
        task_spec = (
            TaskBuilder.deployment(agent_id, "prepare", task_id=task_id)
            .name(f"Prepare deployment for {hostname}")
            .cwd(str(self._repo_root))
            .timeout(7200)
            .requested_by(requested_by)
            .requested_from("server")
            .payload_field("deployment_id", deployment_id)
            .payload_field("repo_url", repo_url or self.get_default_repo_url())
            .payload_field("source_ref", source_ref)
            .payload_field("hostname", hostname)
            .payload_field("display_name", display_name)
            .payload_field("agent_id", agent_id)
            .payload_field("server_ws_url", server_ws_url)
            .payload_field("bootstrap_token", bootstrap_token)
            .payload_field("bootstrap_expires_at", bootstrap_expires_at)
            .component(
                "deployment",
                deployment_id=deployment_id,
                agent_id=agent_id,
                repo_url=repo_url or self.get_default_repo_url(),
                source_ref=source_ref,
                hostname=hostname,
                display_name=display_name,
                server_ws_url=server_ws_url,
                bootstrap_token=bootstrap_token,
                bootstrap_expires_at=bootstrap_expires_at,
            )
            .build()
        )
        await self._registry_db.create_deployment(deployment_id, agent_id, hostname, repo_url, source_ref, requested_by, task_id)

        if self._task_service is None:
            raise RuntimeError("TaskService is not configured for DeploymentService")
        await self._task_service.create_and_dispatch(task_spec)

        deployment = await self._registry_db.get_deployment(deployment_id)
        return deployment or {"id": deployment_id, "status": "queued"}

    async def dispatch_task(self, task: DeploymentTaskSpec) -> TaskDispatchResult:
        if task.operation != "prepare":
            return TaskDispatchResult(accepted=False, status="failed", error=f"Unsupported deployment task operation: {task.operation}")

        payload = task.payload
        deployment_id = str(payload.get("deployment_id") or "").strip()
        hostname = str(payload.get("hostname") or "").strip()
        display_name = str(payload.get("display_name") or hostname).strip()
        repo_url = str(payload.get("repo_url") or self.get_default_repo_url()).strip()
        source_ref = str(payload.get("source_ref") or "main").strip() or "main"
        server_ws_url = str(payload.get("server_ws_url") or "").strip()
        bootstrap_token = str(payload.get("bootstrap_token") or "").strip()
        bootstrap_expires_at = int(payload.get("bootstrap_expires_at") or 0)
        agent_id = str(payload.get("agent_id") or task.agent_id).strip()

        if not deployment_id or not hostname or not agent_id or not server_ws_url or not bootstrap_token or bootstrap_expires_at <= 0:
            return TaskDispatchResult(accepted=False, status="failed", error="Deployment task payload is incomplete")

        prepare_task = asyncio.create_task(
            self._run_prepare(
                deployment_id=deployment_id,
                task_id=task.id,
                agent_id=agent_id,
                hostname=hostname,
                display_name=display_name,
                repo_url=repo_url,
                source_ref=source_ref,
                server_ws_url=server_ws_url,
                bootstrap_token=bootstrap_token,
                bootstrap_expires_at=bootstrap_expires_at,
            )
        )
        self._tasks[deployment_id] = prepare_task
        prepare_task.add_done_callback(lambda _: self._tasks.pop(deployment_id, None))
        return TaskDispatchResult(accepted=True, status="running")

    async def _run_prepare(
        self,
        *,
        deployment_id: str,
        task_id: str,
        agent_id: str,
        hostname: str,
        display_name: str,
        repo_url: str,
        source_ref: str,
        server_ws_url: str,
        bootstrap_token: str,
        bootstrap_expires_at: int,
    ):
        build_log_parts: list[str] = []
        artifact_root = self._artifacts_root / deployment_id
        worktree_dir = artifact_root / "_worktree"
        package_dir = artifact_root / "package"
        latest_dir = self._repo_root / "artifacts" / "latest"
        started_at = int(time.time())

        await self._registry_db.update_deployment(deployment_id, status="building", started_at=started_at, task_id=task_id)
        self._append_task_log(task_id, f"Starting deployment prepare for {hostname} ({source_ref})")

        try:
            artifact_root.mkdir(parents=True, exist_ok=True)

            commit_sha = (await self._run_command(
                ["git", "rev-parse", source_ref],
                cwd=self._repo_root,
                task_id=task_id,
            )).strip()
            build_log_parts.append(f"Resolved {source_ref} -> {commit_sha}")

            if worktree_dir.exists():
                shutil.rmtree(worktree_dir, ignore_errors=True)

            await self._run_command(
                ["git", "worktree", "add", "--detach", str(worktree_dir), commit_sha],
                cwd=self._repo_root,
                task_id=task_id,
            )
            build_log_parts.append(f"Created worktree: {worktree_dir}")

            python_exe = self._repo_root / "env" / "Scripts" / "python.exe"
            if not python_exe.exists():
                raise RuntimeError(f"Python environment not found: {python_exe}")

            build_output = await self._run_command(
                [str(python_exe), "-m", "PyInstaller", "--clean", "agent_service.spec"],
                cwd=worktree_dir,
                task_id=task_id,
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
            install_script_path.write_text(self._build_install_script(deployment_id), encoding="utf-8")

            latest_dir.mkdir(parents=True, exist_ok=True)
            installer_copy_path = latest_dir / f"install-{deployment_id}.ps1"
            installer_copy_path.write_text(self._build_install_script(deployment_id), encoding="utf-8")
            (latest_dir / "install-latest.ps1").write_text(self._build_install_script(deployment_id), encoding="utf-8")

            manifest_path = package_dir / "deployment-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "deployment_id": deployment_id,
                        "agent_id": agent_id,
                        "hostname": hostname,
                        "repo_url": repo_url,
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
                installer_copy_path=str(installer_copy_path),
                build_log="\n\n".join(build_log_parts),
                completed_at=completed_at,
            )
            await self._task_db.update_task_status(task_id, "completed", actor="server")
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
            self._append_task_log(task_id, f"ERROR: {exc}")
            await self._registry_db.update_deployment(
                deployment_id,
                status="failed",
                error=str(exc),
                build_log="\n\n".join(build_log_parts),
                completed_at=completed_at,
            )
            await self._task_db.update_task_status(task_id, "failed", error=str(exc), actor="server")
            await self._registry_db.upsert_agent(agent_id, hostname=hostname, display_name=display_name, status="deploy_failed")
        finally:
            if worktree_dir.exists():
                try:
                    await self._run_command(["git", "worktree", "remove", "--force", str(worktree_dir)], cwd=self._repo_root, task_id=task_id)
                except Exception as cleanup_error:
                    logger.warning("Failed to remove worktree %s: %s", worktree_dir, cleanup_error)
            try:
                await self._run_command(["git", "worktree", "prune"], cwd=self._repo_root, task_id=task_id)
            except Exception as prune_error:
                logger.debug("git worktree prune failed: %s", prune_error)

    async def _run_command(self, args: list[str], cwd: Path, task_id: str | None = None) -> str:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output_parts: list[str] = []
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            chunk = line.decode("utf-8", errors="replace")
            output_parts.append(chunk)
            if task_id:
                self._append_task_log(task_id, chunk.rstrip("\n"))
        await process.wait()
        output = "".join(output_parts)
        if process.returncode != 0:
            raise RuntimeError(f"Command failed ({process.returncode}): {' '.join(args)}\n{output}")
        return output.strip()

    def _append_task_log(self, task_id: str, content: str):
        if not content:
            return
        self._task_db.append_log(task_id, "stdout", content, 0)

    def _build_install_script(self, deployment_id: str) -> str:
        artifact_share_root = self.get_artifact_share_root().replace("\"", "`\"")
        return textwrap.dedent(
            f"""
            param(
                [string]$InstallRoot = "C:\\agent\\MyOrciestra",
                [string]$ServiceName = "VmAgent",
                [string]$ArtifactId = "{deployment_id}",
                [string]$ArtifactSourceRoot = "{artifact_share_root}",
                [string]$PackagePath = ""
            )

            function Test-PackageDirectory {{
                param([string]$CandidatePath)
                if ([string]::IsNullOrWhiteSpace($CandidatePath)) {{
                    return $false
                }}

                $item = Get-Item -LiteralPath $CandidatePath -ErrorAction SilentlyContinue
                if (-not $item) {{
                    return $false
                }}

                $directoryPath = $null
                if ($item.PSIsContainer) {{
                    $directoryPath = $item.FullName
                }} else {{
                    $directoryPath = $item.DirectoryName
                }}
                if ([string]::IsNullOrWhiteSpace($directoryPath)) {{
                    return $false
                }}

                $exeCandidate = Join-Path $directoryPath "agent_service.exe"
                return Test-Path -LiteralPath $exeCandidate -ErrorAction SilentlyContinue
            }}

            function Resolve-PackagePath {{
                param([string]$RootPath, [string]$DeploymentId)
                if ([string]::IsNullOrWhiteSpace($RootPath)) {{
                    return $null
                }}
                return Join-Path (Join-Path $RootPath $DeploymentId) "package"
            }}

            function Get-BootstrapMetadata {{
                param([string]$PackageRoot)

                $bootstrapPath = Join-Path $PackageRoot "agent.bootstrap.json"
                if (-not (Test-Path -LiteralPath $bootstrapPath -ErrorAction SilentlyContinue)) {{
                    return $null
                }}

                try {{
                    return Get-Content -LiteralPath $bootstrapPath -Raw | ConvertFrom-Json
                }} catch {{
                    throw ("Failed to parse bootstrap metadata from {{0}}: {{1}}" -f $bootstrapPath, $_.Exception.Message)
                }}
            }}

            function Resolve-PackageRoot {{
                param(
                    [string]$ExplicitPath,
                    [string]$ScriptRoot,
                    [string]$ArtifactRoot,
                    [string]$DeploymentId
                )

                $candidates = @()
                if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {{
                    $candidates += $ExplicitPath
                    $candidates += (Join-Path $ExplicitPath "package")
                }}

                if (-not [string]::IsNullOrWhiteSpace($ScriptRoot)) {{
                    $candidates += $ScriptRoot
                    $candidates += (Join-Path $ScriptRoot "package")

                    $artifactsRoot = Split-Path $ScriptRoot -Parent
                    if (-not [string]::IsNullOrWhiteSpace($artifactsRoot)) {{
                        $candidates += (Join-Path $artifactsRoot (Join-Path "deployments" (Join-Path $DeploymentId "package")))
                    }}
                }}

                if (-not [string]::IsNullOrWhiteSpace($ArtifactRoot)) {{
                    $candidates += (Resolve-PackagePath -RootPath $ArtifactRoot -DeploymentId $DeploymentId)
                }}

                foreach ($candidate in $candidates) {{
                    if (Test-PackageDirectory -CandidatePath $candidate) {{
                        $item = Get-Item -LiteralPath $candidate -ErrorAction SilentlyContinue
                        if ($item -and $item.PSIsContainer) {{
                            return $item.FullName
                        }}
                        if ($item -and $item.DirectoryName) {{
                            return $item.DirectoryName
                        }}
                    }}
                }}

                return $null
            }}

            $PackageRoot = Resolve-PackageRoot -ExplicitPath $PackagePath -ScriptRoot $PSScriptRoot -ArtifactRoot $ArtifactSourceRoot -DeploymentId $ArtifactId
            if (-not $PackageRoot) {{
                throw "Artifact package not found. Use -PackagePath for a local package folder, or run this installer from artifacts\\latest with a sibling deployments\\<artifactId>\\package folder."
            }}

            $BootstrapMetadata = Get-BootstrapMetadata -PackageRoot $PackageRoot
            if ($BootstrapMetadata -and $BootstrapMetadata.hostname) {{
                $expectedHostname = [string]$BootstrapMetadata.hostname
                $localHostname = [string]$env:COMPUTERNAME
                if ($expectedHostname -and $localHostname -and $expectedHostname.ToLowerInvariant() -ne $localHostname.ToLowerInvariant()) {{
                    throw "Bootstrap package is bound to host '$expectedHostname', but this machine is '$localHostname'. Copy the package to the intended VM or prepare a deployment for this host."
                }}
            }}

            $ExePath = Join-Path $PackageRoot "agent_service.exe"
            $BootstrapPath = Join-Path $PackageRoot "agent.bootstrap.json"

            if (-not (Test-Path $ExePath)) {{
                throw "agent_service.exe not found in package directory"
            }}

            New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

            Copy-Item $ExePath (Join-Path $InstallRoot "agent_service.exe") -Force
            if (Test-Path $BootstrapPath) {{
                Copy-Item $BootstrapPath (Join-Path $InstallRoot "agent.bootstrap.json") -Force
            }}

            $InstalledExe = Join-Path $InstallRoot "agent_service.exe"

            if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {{
                Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
                & $InstalledExe remove 2>$null
                Start-Sleep -Seconds 1
            }}

            & $InstalledExe install
            Start-Sleep -Seconds 1
            Start-Service -Name $ServiceName
            Get-Service -Name $ServiceName
            """
        ).strip() + "\n"