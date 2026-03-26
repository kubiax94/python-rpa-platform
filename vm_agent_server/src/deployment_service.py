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
from typing import Any

from vm_agent_server.src.agent_registry_db import AgentRegistryDB, hash_token
from vm_agent_server.src.task_db import TaskDB

logger = logging.getLogger(__name__)


class DeploymentService:
    def __init__(self, registry_db: AgentRegistryDB, task_db: TaskDB, repo_root: Path):
        self._registry_db = registry_db
        self._task_db = task_db
        self._repo_root = repo_root
        self._artifacts_root = repo_root / "artifacts" / "deployments"
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_lock = asyncio.Lock()

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
        await self._task_db.create_task(
            task_id=task_id,
            agent_id=agent_id,
            script=f"prepare_deployment repo={repo_url or self.get_default_repo_url()} ref={source_ref}",
            name=f"Prepare deployment for {hostname}",
            cwd=str(self._repo_root),
            timeout_sec=7200,
            requested_by=requested_by,
            requested_from="server",
        )
        await self._task_db.update_task_status(task_id, "running", actor="server")
        await self._registry_db.create_deployment(deployment_id, agent_id, hostname, repo_url, source_ref, requested_by, task_id)

        task = asyncio.create_task(
            self._run_prepare(
                deployment_id=deployment_id,
                task_id=task_id,
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
        self._tasks[deployment_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(deployment_id, None))

        deployment = await self._registry_db.get_deployment(deployment_id)
        return deployment or {"id": deployment_id, "status": "queued"}

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

            function Test-PathSafe {{
                param([string]$CandidatePath)
                if ([string]::IsNullOrWhiteSpace($CandidatePath)) {{
                    return $false
                }}

                try {{
                    return Test-Path -LiteralPath $CandidatePath
                }} catch {{
                    return $false
                }}
            }}

            function Normalize-DirectoryPath {{
                param([string]$CandidatePath)
                if ([string]::IsNullOrWhiteSpace($CandidatePath)) {{
                    return $null
                }}

                $resolved = Resolve-Path -LiteralPath $CandidatePath -ErrorAction SilentlyContinue
                if ($resolved) {{
                    return $resolved.Path
                }}

                $combined = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $CandidatePath))
                $resolvedCombined = Resolve-Path -LiteralPath $combined -ErrorAction SilentlyContinue
                if ($resolvedCombined) {{
                    return $resolvedCombined.Path
                }}

                return $combined
            }}

            function Test-PackageDirectory {{
                param([string]$CandidatePath)
                if ([string]::IsNullOrWhiteSpace($CandidatePath)) {{
                    return $false
                }}

                $normalizedPath = Normalize-DirectoryPath -CandidatePath $CandidatePath
                if ([string]::IsNullOrWhiteSpace($normalizedPath)) {{
                    return $false
                }}

                if (-not (Test-PathSafe -CandidatePath $normalizedPath)) {{
                    return $false
                }}

                $item = Get-Item -LiteralPath $normalizedPath -ErrorAction SilentlyContinue
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
                return Test-PathSafe -CandidatePath $exeCandidate
            }}

            function Resolve-PackagePath {{
                param([string]$RootPath, [string]$DeploymentId)
                return Join-Path (Join-Path $RootPath $DeploymentId) "package"
            }}

            function Get-BootstrapMetadata {{
                param([string]$PackageRoot)

                $bootstrapPath = Join-Path $PackageRoot "agent.bootstrap.json"
                if (-not (Test-PathSafe -CandidatePath $bootstrapPath)) {{
                    return $null
                }}

                try {{
                    return Get-Content -LiteralPath $bootstrapPath -Raw | ConvertFrom-Json
                }} catch {{
                    throw "Failed to parse bootstrap metadata from ${bootstrapPath}: $($_.Exception.Message)"
                }}
            }}

            function Resolve-LocalPackagePath {{
                param([string]$ExplicitPath)

                $candidates = @()
                if ($ExplicitPath) {{
                    $candidates += $ExplicitPath
                    $candidates += (Join-Path $ExplicitPath "package")
                }}

                if ($PSScriptRoot) {{
                    $candidates += $PSScriptRoot
                    $candidates += (Join-Path $PSScriptRoot "package")
                }}

                $candidates += (Get-Location).Path
                $candidates += (Join-Path (Get-Location).Path "package")

                foreach ($candidate in $candidates) {{
                    if (Test-PackageDirectory -CandidatePath $candidate) {{
                        $item = Get-Item -LiteralPath (Normalize-DirectoryPath -CandidatePath $candidate) -ErrorAction SilentlyContinue
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

            function Mount-ArtifactShare {{
                param([string]$RootPath)
                $driveName = "AGENTART"
                if (Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue) {{
                    Remove-PSDrive -Name $driveName -Force -ErrorAction SilentlyContinue
                }}

                $credential = Get-Credential -Message "Credentials required to read deployment artifacts"
                New-PSDrive -Name $driveName -PSProvider FileSystem -Root $RootPath -Credential $credential -Scope Script | Out-Null
                return "$driveName`:"
            }}

            $PackageRoot = Resolve-LocalPackagePath -ExplicitPath $PackagePath
            if (-not $PackageRoot) {{
                $PackageRoot = Resolve-PackagePath -RootPath $ArtifactSourceRoot -DeploymentId $ArtifactId
            }}

            if (-not (Test-PathSafe -CandidatePath $PackageRoot)) {{
                if (-not [string]::IsNullOrWhiteSpace($ArtifactSourceRoot) -and $ArtifactSourceRoot.StartsWith("\\")) {{
                    $mountedRoot = Mount-ArtifactShare -RootPath $ArtifactSourceRoot
                    $PackageRoot = Resolve-PackagePath -RootPath $mountedRoot -DeploymentId $ArtifactId
                }}
            }}

            if (-not (Test-PathSafe -CandidatePath $PackageRoot)) {{
                throw "Artifact package not found. Provide -PackagePath with a local package folder or ensure the share path is reachable: $ArtifactSourceRoot"
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