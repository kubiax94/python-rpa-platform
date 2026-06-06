from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import subprocess
import textwrap
import time
import uuid
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import TYPE_CHECKING, Any

from vm_agent_server.src.persistence.agent_registry_db import AgentRegistryDB, hash_token
from vm_agent_server.src.guacamole.bridge import provision_guacamole_agent_target_with_diagnostics
from vm_agent_server.src.guacamole.mapping import build_agent_guacamole_mapping
from vm_agent_server.src.settings.service import ServerSettingsService
from vm_agent_server.src.tasks.db import TaskDB
from vm_agent_server.src.tasks.dispatcher import TaskDispatchResult
from vm_agent_server.src.tasks.models import DeploymentTaskSpec, TaskBuilder

if TYPE_CHECKING:
    from vm_agent_server.src.tasks.service import TaskService

logger = logging.getLogger(__name__)
DEFAULT_RELEASE_ASSET_NAME = "agent_service.exe"
DEFAULT_RELEASE_CHECKSUM_NAME = "agent_service.exe.sha256"


def _normalize_hostname_value(value: str) -> tuple[str, str]:
    cleaned = value.strip().rstrip(".").lower()
    short_name = cleaned.split(".", 1)[0] if cleaned else ""
    return cleaned, short_name


def _resolve_bootstrap_hostnames(hostname: str) -> tuple[str, str]:
    full_name, short_name = _normalize_hostname_value(hostname)
    if "." in full_name:
        return hostname.strip(), short_name
    return "", hostname.strip()


class DeploymentService:
    def __init__(
        self,
        registry_db: AgentRegistryDB,
        task_db: TaskDB,
        repo_root: Path,
        server_settings_service: ServerSettingsService | None = None,
    ):
        self._registry_db = registry_db
        self._task_db = task_db
        self._repo_root = repo_root
        self._server_settings_service = server_settings_service
        self._artifacts_root = repo_root / "artifacts" / "deployments"
        self._release_cache_root = repo_root / "artifacts" / "release-proxy"
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_lock = asyncio.Lock()
        self._task_service: TaskService | None = None

    def set_task_service(self, task_service: "TaskService") -> None:
        self._task_service = task_service

    def set_server_settings_service(self, server_settings_service: ServerSettingsService) -> None:
        self._server_settings_service = server_settings_service

    def get_default_repo_url(self) -> str:
        if self._server_settings_service is not None:
            configured = self._server_settings_service.get_snapshot().deployment.default_repo_url.strip()
            if configured:
                return configured
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
        if self._server_settings_service is not None:
            configured = self._server_settings_service.get_snapshot().deployment.artifact_share_root.strip()
            if configured:
                return configured
        override = os.getenv("VM_AGENT_ARTIFACT_SHARE_ROOT")
        if override:
            return override
        return f"\\\\{socket.gethostname()}\\agent\\DevOPS\\artifacts\\deployments"

    def get_latest_installer_share_template(self) -> str:
        if self._server_settings_service is not None:
            configured = self._server_settings_service.get_snapshot().deployment.latest_installer_share_template.strip()
            if configured:
                return configured
        share_root = self.get_artifact_share_root()
        if share_root.endswith("\\deployments"):
            return share_root[: -len("\\deployments")] + "\\latest\\install-{deployment_id}.ps1"
        return share_root + "\\..\\latest\\install-{deployment_id}.ps1"

    def get_release_asset_name(self) -> str:
        return os.getenv("VM_AGENT_RELEASE_ASSET_NAME", DEFAULT_RELEASE_ASSET_NAME).strip() or DEFAULT_RELEASE_ASSET_NAME

    def get_release_checksum_name(self) -> str:
        return os.getenv("VM_AGENT_RELEASE_CHECKSUM_NAME", DEFAULT_RELEASE_CHECKSUM_NAME).strip() or DEFAULT_RELEASE_CHECKSUM_NAME

    def _get_github_token(self) -> str:
        return os.getenv("VM_AGENT_GITHUB_TOKEN", "").strip() or os.getenv("GITHUB_TOKEN", "").strip()

    def _get_github_repo_slug(self) -> str:
        repo_url = self.get_default_repo_url().strip()
        if not repo_url:
            return ""

        normalized = repo_url
        if normalized.endswith(".git"):
            normalized = normalized[:-4]

        if normalized.startswith("git@github.com:"):
            return normalized[len("git@github.com:") :].strip("/")

        parsed = urlparse(normalized)
        if parsed.netloc.lower() == "github.com":
            return parsed.path.strip("/")

        return ""

    def _github_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "vm-agent-server",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = self._get_github_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _read_json_url(self, url: str) -> Any:
        request = Request(url, headers=self._github_headers())
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _read_text_url(self, url: str) -> str:
        request = Request(url, headers=self._github_headers())
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")

    def _extract_checksum(self, checksum_text: str, expected_name: str) -> str:
        for raw_line in checksum_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 1:
                return parts[0].strip().lower()
            if len(parts) >= 2:
                candidate_hash = parts[0].strip().lower()
                candidate_name = parts[-1].strip().lstrip("*")
                if candidate_name == expected_name:
                    return candidate_hash
        return ""

    def _build_release_record(self, release: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(release, dict):
            return None

        asset_name = self.get_release_asset_name()
        checksum_name = self.get_release_checksum_name()
        assets = release.get("assets") if isinstance(release.get("assets"), list) else []
        binary_asset = next((asset for asset in assets if isinstance(asset, dict) and asset.get("name") == asset_name), None)
        checksum_asset = next((asset for asset in assets if isinstance(asset, dict) and asset.get("name") == checksum_name), None)
        if not binary_asset:
            return None

        checksum_value = ""
        checksum_url = str((checksum_asset or {}).get("browser_download_url") or "").strip()
        if checksum_url:
            checksum_text = self._read_text_url(checksum_url)
            checksum_value = self._extract_checksum(checksum_text, asset_name)

        published_at_raw = str(release.get("published_at") or "").strip()
        published_at = None
        if published_at_raw:
            try:
                published_at = int(time.mktime(time.strptime(published_at_raw, "%Y-%m-%dT%H:%M:%SZ")))
            except ValueError:
                published_at = None

        release_id = str(release.get("id") or "").strip() or None
        tag_name = str(release.get("tag_name") or "").strip()
        version = tag_name.removeprefix("v") or tag_name or str(release.get("name") or "").strip()
        return {
            "release_id": release_id,
            "version": version,
            "tag_name": tag_name,
            "commit_sha": str(release.get("target_commitish") or "").strip(),
            "artifact_url": str(binary_asset.get("browser_download_url") or "").strip(),
            "artifact_sha256": checksum_value,
            "workflow_run_id": str(((release.get("author") if isinstance(release.get("author"), dict) else {}).get("id") or "")).strip() or None,
            "published_at": published_at,
            "metadata": {
                "release_name": str(release.get("name") or "").strip(),
                "html_url": str(release.get("html_url") or "").strip(),
                "prerelease": bool(release.get("prerelease")),
                "draft": bool(release.get("draft")),
                "asset_name": asset_name,
                "checksum_asset_name": checksum_name,
            },
        }

    def _sync_github_releases(self, limit: int = 20) -> list[dict[str, Any]]:
        repo_slug = self._get_github_repo_slug()
        if not repo_slug:
            return []

        api_url = f"https://api.github.com/repos/{repo_slug}/releases?per_page={limit}"
        payload = self._read_json_url(api_url)
        if not isinstance(payload, list):
            return []

        releases: list[dict[str, Any]] = []
        for entry in payload:
            record = self._build_release_record(entry)
            if record is not None:
                releases.append(record)
        return releases

    async def sync_release_metadata_from_github(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            releases = await asyncio.to_thread(self._sync_github_releases, limit)
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to sync release metadata from GitHub: %s", exc)
            return await self._registry_db.get_releases(limit=limit)

        synced: list[dict[str, Any]] = []
        for release in releases:
            persisted = await self._registry_db.upsert_release_from_source(
                version=release["version"],
                commit_sha=release["commit_sha"],
                artifact_url=release["artifact_url"],
                artifact_sha256=release["artifact_sha256"],
                tag_name=release["tag_name"],
                workflow_run_id=release["workflow_run_id"],
                published_at=release["published_at"],
                metadata=release["metadata"],
                release_id=release["release_id"],
            )
            if persisted is not None:
                synced.append(persisted)
        return synced or await self._registry_db.get_releases(limit=limit)

    async def get_prepare_config(self) -> dict[str, Any]:
        active = await self._registry_db.get_active_deployment()
        releases = await self.sync_release_metadata_from_github(limit=20)
        return {
            "default_repo_url": self.get_default_repo_url(),
            "artifact_share_root": self.get_artifact_share_root(),
            "latest_installer_share_template": self.get_latest_installer_share_template(),
            "active_deployment": active,
            "latest_release": releases[0] if releases else None,
            "releases": releases,
        }

    async def get_releases_config(self, limit: int = 20) -> dict[str, Any]:
        releases = await self.sync_release_metadata_from_github(limit=limit)
        return {
            "repo_slug": self._get_github_repo_slug(),
            "repo_url": self.get_default_repo_url(),
            "latest_release": releases[0] if releases else None,
            "releases": releases,
        }

    async def _resolve_prepare_release(self, release_id: str | None) -> dict[str, Any]:
        selected_release_id = (release_id or "").strip()
        releases = await self.sync_release_metadata_from_github(limit=20)
        if selected_release_id:
            for release in releases:
                if str(release.get("id") or "").strip() == selected_release_id:
                    return release
            persisted = await self._registry_db.get_release(selected_release_id)
            if persisted is not None:
                return persisted
            raise RuntimeError(f"Release not found: {selected_release_id}")

        if releases:
            return releases[0]

        latest = await self._registry_db.get_latest_release()
        if latest is not None:
            return latest

        raise RuntimeError("No agent release is available for deployment")

    async def prepare_deployment(
        self,
        *,
        agent_id: str,
        hostname: str,
        display_name: str,
        guacamole_target_host: str,
        guacamole_username: str,
        guacamole_domain: str,
        guacamole_password: str,
        guacamole_secret: str,
        guacamole_group_name: str,
        guacamole_connection_name: str,
        release_id: str | None,
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
        selected_release = await self._resolve_prepare_release(release_id)
        selected_release_id = str(selected_release.get("id") or "").strip()
        if not selected_release_id:
            raise RuntimeError("Selected release is missing an id")

        artifact_url = str(selected_release.get("artifact_url") or "").strip()
        if not artifact_url:
            raise RuntimeError(f"Selected release {selected_release_id} does not have a downloadable artifact")

        artifact_sha256 = str(selected_release.get("artifact_sha256") or "").strip().lower()
        tag_name = str(selected_release.get("tag_name") or "").strip()
        version = str(selected_release.get("version") or tag_name or selected_release_id).strip()
        commit_sha = str(selected_release.get("commit_sha") or "").strip()
        guacamole_mapping = build_agent_guacamole_mapping(
            agent_id=agent_id,
            hostname=hostname,
            display_name=display_name,
            target_host=guacamole_target_host,
            username=guacamole_username,
            domain=guacamole_domain,
            group_name=guacamole_group_name,
            connection_name=guacamole_connection_name,
        )
        guacamole_mapping, guacamole_provisioning = await asyncio.to_thread(
            provision_guacamole_agent_target_with_diagnostics,
            agent_id,
            hostname,
            guacamole_mapping,
            template_values={
                "password": guacamole_password,
                "secret": guacamole_secret,
            },
        )

        await self._registry_db.upsert_agent(
            agent_id,
            hostname=hostname,
            display_name=display_name,
            status="provisioning",
            connection_status="offline",
            last_deployment_id=deployment_id,
            metadata={"guacamole": guacamole_mapping},
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
            .payload_field("release_id", selected_release_id)
            .payload_field("release_version", version)
            .payload_field("release_tag_name", tag_name)
            .payload_field("artifact_url", artifact_url)
            .payload_field("artifact_sha256", artifact_sha256)
            .payload_field("commit_sha", commit_sha)
            .payload_field("hostname", hostname)
            .payload_field("display_name", display_name)
            .payload_field("agent_id", agent_id)
            .payload_field("guacamole", guacamole_mapping)
            .payload_field("server_ws_url", server_ws_url)
            .payload_field("bootstrap_token", bootstrap_token)
            .payload_field("bootstrap_expires_at", bootstrap_expires_at)
            .component(
                "deployment",
                deployment_id=deployment_id,
                agent_id=agent_id,
                release_id=selected_release_id,
                release_version=version,
                release_tag_name=tag_name,
                artifact_url=artifact_url,
                artifact_sha256=artifact_sha256,
                commit_sha=commit_sha,
                hostname=hostname,
                display_name=display_name,
                guacamole=guacamole_mapping,
                server_ws_url=server_ws_url,
                bootstrap_token=bootstrap_token,
                bootstrap_expires_at=bootstrap_expires_at,
            )
            .build()
        )
        await self._registry_db.create_deployment(
            deployment_id,
            agent_id,
            hostname,
            requested_by,
            task_id,
            release_id=selected_release_id,
            metadata={
                "guacamole_provisioning": guacamole_provisioning,
                "release": {
                    "id": selected_release_id,
                    "version": version,
                    "tag_name": tag_name,
                    "artifact_url": artifact_url,
                    "artifact_sha256": artifact_sha256,
                },
            },
        )

        if self._task_service is None:
            raise RuntimeError("TaskService is not configured for DeploymentService")
        submission = await self._task_service.create_and_dispatch(task_spec)
        if not submission.dispatch.accepted:
            completed_at = int(time.time())
            error = submission.dispatch.error or "Deployment dispatch failed"
            await self._registry_db.update_deployment(
                deployment_id,
                status="failed",
                release_id=selected_release_id,
                error=error,
                completed_at=completed_at,
                task_id=task_id,
            )
            await self._registry_db.upsert_agent(
                agent_id,
                hostname=hostname,
                display_name=display_name,
                status="deploy_failed",
                connection_status="offline",
                last_deployment_id=deployment_id,
            )

        deployment = await self._registry_db.get_deployment(deployment_id)
        return deployment or {"id": deployment_id, "status": "queued"}

    async def recover_interrupted_deployments(self) -> int:
        recovered = 0
        now = int(time.time())
        active_deployments = await self._registry_db.get_active_deployments()
        for deployment in active_deployments:
            deployment_id = str(deployment.get("id") or "").strip()
            if not deployment_id or deployment_id in self._tasks:
                continue

            agent_id = str(deployment.get("agent_id") or "").strip()
            hostname = str(deployment.get("hostname") or "").strip()
            status = str(deployment.get("status") or "queued").strip() or "queued"
            error = f"Deployment prepare was interrupted while in '{status}'. The server was restarted before the release package was prepared."
            logger.warning("Recovering interrupted deployment %s stuck in status=%s", deployment_id, status)
            await self._registry_db.update_deployment(
                deployment_id,
                status="failed",
                error=error,
                completed_at=now,
            )
            if agent_id:
                await self._registry_db.upsert_agent(
                    agent_id,
                    hostname=hostname,
                    status="deploy_failed",
                    connection_status="offline",
                    last_deployment_id=deployment_id,
                )
            recovered += 1
        return recovered

    async def dispatch_task(self, task: DeploymentTaskSpec) -> TaskDispatchResult:
        if task.operation != "prepare":
            return TaskDispatchResult(accepted=False, status="failed", error=f"Unsupported deployment task operation: {task.operation}")

        payload = task.payload
        deployment_id = str(payload.get("deployment_id") or "").strip()
        hostname = str(payload.get("hostname") or "").strip()
        display_name = str(payload.get("display_name") or hostname).strip()
        release_id = str(payload.get("release_id") or "").strip()
        release_version = str(payload.get("release_version") or "").strip()
        release_tag_name = str(payload.get("release_tag_name") or "").strip()
        artifact_url = str(payload.get("artifact_url") or "").strip()
        artifact_sha256 = str(payload.get("artifact_sha256") or "").strip().lower()
        commit_sha = str(payload.get("commit_sha") or "").strip()
        server_ws_url = str(payload.get("server_ws_url") or "").strip()
        bootstrap_token = str(payload.get("bootstrap_token") or "").strip()
        bootstrap_expires_at = int(payload.get("bootstrap_expires_at") or 0)
        agent_id = str(payload.get("agent_id") or task.agent_id).strip()
        guacamole_mapping = payload.get("guacamole") if isinstance(payload.get("guacamole"), dict) else {}

        if (
            not deployment_id
            or not hostname
            or not agent_id
            or not release_id
            or not artifact_url
            or not server_ws_url
            or not bootstrap_token
            or bootstrap_expires_at <= 0
        ):
            return TaskDispatchResult(accepted=False, status="failed", error="Deployment task payload is incomplete")

        started_at = int(time.time())
        await self._registry_db.update_deployment(
            deployment_id,
            release_id=release_id,
            status="preparing",
            tag_name=release_tag_name,
            commit_sha=commit_sha,
            started_at=started_at,
            task_id=task.id,
        )

        prepare_task = asyncio.create_task(
            self._run_prepare(
                deployment_id=deployment_id,
                task_id=task.id,
                agent_id=agent_id,
                hostname=hostname,
                display_name=display_name,
                guacamole_mapping=guacamole_mapping,
                release_id=release_id,
                release_version=release_version,
                release_tag_name=release_tag_name,
                artifact_url=artifact_url,
                artifact_sha256=artifact_sha256,
                commit_sha=commit_sha,
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
        release_id: str,
        release_version: str,
        release_tag_name: str,
        artifact_url: str,
        artifact_sha256: str,
        commit_sha: str,
        hostname: str,
        display_name: str,
        guacamole_mapping: dict[str, Any],
        server_ws_url: str,
        bootstrap_token: str,
        bootstrap_expires_at: int,
    ):
        build_log_parts: list[str] = []
        release_label = release_tag_name or release_version or release_id
        self._append_task_log(task_id, f"Starting deployment prepare for {hostname} ({release_label})")
        artifact_root = self._artifacts_root / deployment_id
        package_dir = artifact_root / "package"
        latest_dir = self._repo_root / "artifacts" / "latest"

        try:
            artifact_root.mkdir(parents=True, exist_ok=True)
            package_dir.mkdir(parents=True, exist_ok=True)
            artifact_exe = package_dir / "agent_service.exe"
            downloaded_sha256 = await asyncio.to_thread(
                self._download_release_artifact,
                artifact_url,
                artifact_exe,
                task_id,
            )
            build_log_parts.append(f"Downloaded release artifact: {artifact_url}")
            if artifact_sha256:
                build_log_parts.append(f"Expected SHA256: {artifact_sha256}")
                build_log_parts.append(f"Downloaded SHA256: {downloaded_sha256}")
                if downloaded_sha256 != artifact_sha256:
                    raise RuntimeError(
                        f"Downloaded artifact checksum mismatch for release {release_label}: {downloaded_sha256} != {artifact_sha256}"
                    )
            elif downloaded_sha256:
                build_log_parts.append(f"Downloaded SHA256: {downloaded_sha256}")

            bootstrap_path = package_dir / "agent.bootstrap.json"
            bootstrap_fqdn, bootstrap_hostname = _resolve_bootstrap_hostnames(hostname)
            bootstrap_payload = {
                "agent_id": agent_id,
                "hostname": bootstrap_hostname or hostname,
                "fqdn": bootstrap_fqdn,
                "display_name": display_name,
                "guacamole": guacamole_mapping,
                "server_url": server_ws_url,
                "bootstrap_token": bootstrap_token,
                "bootstrap_expires_at": bootstrap_expires_at,
                "deployment_id": deployment_id,
                "release_id": release_id,
                "release_version": release_version,
                "tag_name": release_tag_name,
                "artifact_url": artifact_url,
                "artifact_sha256": artifact_sha256 or downloaded_sha256,
                "commit_sha": commit_sha,
            }
            bootstrap_path.write_text(json.dumps(bootstrap_payload, indent=2), encoding="utf-8")

            install_script_path = package_dir / "install.ps1"
            install_script_path.write_text(self._build_install_script(deployment_id), encoding="utf-8")

            latest_dir.mkdir(parents=True, exist_ok=True)
            installer_copy_path = latest_dir / f"install-{deployment_id}.ps1"
            installer_copy_path.write_text(self._build_install_script(deployment_id), encoding="utf-8")
            (latest_dir / "install-latest.ps1").write_text(self._build_install_script(deployment_id), encoding="utf-8")

            package_zip_path = artifact_root / "package.zip"
            self._create_package_zip(package_dir, package_zip_path)

            manifest_path = package_dir / "deployment-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "deployment_id": deployment_id,
                        "agent_id": agent_id,
                        "hostname": hostname,
                        "display_name": display_name,
                        "guacamole": guacamole_mapping,
                        "release_id": release_id,
                        "release_version": release_version,
                        "tag_name": release_tag_name,
                        "artifact_url": artifact_url,
                        "artifact_sha256": artifact_sha256 or downloaded_sha256,
                        "commit_sha": commit_sha,
                        "artifact_exe": artifact_exe.name,
                        "package_zip": package_zip_path.name,
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
                release_id=release_id,
                status="ready",
                commit_sha=commit_sha,
                tag_name=release_tag_name,
                artifact_dir=str(package_dir),
                artifact_exe_path=str(artifact_exe),
                package_zip_path=str(package_zip_path),
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
                current_version=release_version or release_tag_name or commit_sha[:12],
            )
        except Exception as exc:
            completed_at = int(time.time())
            build_log_parts.append(f"ERROR: {exc}")
            self._append_task_log(task_id, f"ERROR: {exc}")
            await self._registry_db.update_deployment(
                deployment_id,
                release_id=release_id,
                status="failed",
                error=str(exc),
                build_log="\n\n".join(build_log_parts),
                completed_at=completed_at,
            )
            await self._task_db.update_task_status(task_id, "failed", error=str(exc), actor="server")
            await self._registry_db.upsert_agent(agent_id, hostname=hostname, display_name=display_name, status="deploy_failed")

    def _download_release_artifact(self, artifact_url: str, destination: Path, task_id: str | None = None) -> str:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = Request(artifact_url, headers=self._github_headers())
        digest = hashlib.sha256()
        with urlopen(request, timeout=120) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)

        checksum = digest.hexdigest().lower()
        if task_id:
            self._append_task_log(task_id, f"Downloaded {destination.name} ({destination.stat().st_size} bytes)")
            self._append_task_log(task_id, f"Computed SHA256: {checksum}")
        return checksum

    def _hash_file_sha256(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest().lower()

    async def get_release_artifact_proxy(self, release_id: str) -> tuple[Path, str]:
        release = await self._resolve_prepare_release(release_id)
        artifact_url = str(release.get("artifact_url") or "").strip()
        if not artifact_url:
            raise RuntimeError(f"Release {release_id} does not expose an artifact URL")

        metadata = release.get("metadata") if isinstance(release.get("metadata"), dict) else {}
        asset_name = str(metadata.get("asset_name") or "").strip() or self.get_release_asset_name()
        cache_dir = self._release_cache_root / release_id
        cached_path = cache_dir / asset_name
        expected_sha256 = str(release.get("artifact_sha256") or "").strip().lower()

        if cached_path.exists():
            if not expected_sha256:
                return cached_path, asset_name
            actual_sha256 = await asyncio.to_thread(self._hash_file_sha256, cached_path)
            if actual_sha256 == expected_sha256:
                return cached_path, asset_name

        downloaded_sha256 = await asyncio.to_thread(self._download_release_artifact, artifact_url, cached_path, None)
        if expected_sha256 and downloaded_sha256 != expected_sha256:
            try:
                cached_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to remove invalid cached release artifact: %s", cached_path)
            raise RuntimeError(
                f"Downloaded artifact checksum mismatch for release {release_id}: {downloaded_sha256} != {expected_sha256}"
            )
        return cached_path, asset_name

    def _append_task_log(self, task_id: str, content: str):
        if not content:
            return
        self._task_db.append_log(task_id, "stdout", content, 0)

    def _create_package_zip(self, package_dir: Path, zip_path: Path) -> None:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source_path in sorted(package_dir.rglob("*")):
                if source_path.is_file():
                    archive.write(source_path, arcname=source_path.relative_to(package_dir))

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
                throw "Artifact package not found. Download package.zip from the server, extract it locally, and run install.ps1 with -PackagePath pointing at the extracted package folder."
            }}

            $BootstrapMetadata = Get-BootstrapMetadata -PackageRoot $PackageRoot
            if ($BootstrapMetadata -and ($BootstrapMetadata.hostname -or $BootstrapMetadata.fqdn)) {{
                $expectedHostname = [string]$BootstrapMetadata.hostname
                $expectedFqdn = [string]$BootstrapMetadata.fqdn
                $localHostname = [string]$env:COMPUTERNAME
                $localFqdn = ""
                try {{
                    $localFqdn = [string][System.Net.Dns]::GetHostEntry('localhost').HostName
                }} catch {{
                    $localFqdn = ""
                }}
                $expectedHostCandidate = if (-not [string]::IsNullOrWhiteSpace($expectedFqdn)) {{ $expectedFqdn }} else {{ $expectedHostname }}
                $expectedHostnameNormalized = $expectedHostCandidate.Trim().TrimEnd('.').ToLowerInvariant()
                $expectedHostnameShort = if ($expectedHostnameNormalized.Contains('.')) {{ $expectedHostnameNormalized.Split('.', 2)[0] }} else {{ $expectedHostnameNormalized }}
                $matchesHost = $false
                foreach ($candidate in @($localHostname, $localFqdn)) {{
                    if ([string]::IsNullOrWhiteSpace($candidate)) {{
                        continue
                    }}
                    $candidateNormalized = $candidate.Trim().TrimEnd('.').ToLowerInvariant()
                    $candidateShort = if ($candidateNormalized.Contains('.')) {{ $candidateNormalized.Split('.', 2)[0] }} else {{ $candidateNormalized }}
                    if (
                        $expectedHostnameNormalized -eq $candidateNormalized -or
                        $expectedHostnameNormalized -eq $candidateShort -or
                        $expectedHostnameShort -eq $candidateNormalized -or
                        $expectedHostnameShort -eq $candidateShort
                    ) {{
                        $matchesHost = $true
                        break
                    }}
                }}
                if (-not $matchesHost) {{
                    $localHostDisplay = if (-not [string]::IsNullOrWhiteSpace($localFqdn)) {{ $localFqdn }} else {{ $localHostname }}
                    throw "Bootstrap package is bound to host '$expectedHostCandidate', but this machine is '$localHostDisplay'. Copy the package to the intended VM or prepare a deployment for this host."
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