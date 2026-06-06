import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vm_agent_server.src.services.deployment_service import DeploymentService
from vm_agent_server.src.tasks.dispatcher import TaskDispatchResult
from vm_agent_server.src.tasks.service import TaskSubmissionResult


class FakeRegistryDB:
    def __init__(self):
        self.deployments = {}
        self.agent_updates = []
        self.bootstrap_tokens = []
        self.releases = {
            "release-1": {
                "id": "release-1",
                "version": "1.2.3",
                "tag_name": "v1.2.3",
                "commit_sha": "abcdef1234567890",
                "artifact_url": "https://example.test/releases/agent_service.exe",
                "artifact_sha256": "deadbeef",
            }
        }

    async def get_active_deployment(self):
        for deployment in self.deployments.values():
            if deployment["status"] in {"queued", "building", "preparing"}:
                return deployment
        return None

    async def get_active_deployments(self):
        return [deployment for deployment in self.deployments.values() if deployment["status"] in {"queued", "building", "preparing"}]

    async def upsert_agent(self, agent_id, **kwargs):
        self.agent_updates.append((agent_id, kwargs))

    async def set_bootstrap_token(self, agent_id, token_hash, expires_at):
        self.bootstrap_tokens.append((agent_id, token_hash, expires_at))

    async def create_deployment(self, deployment_id, agent_id, hostname, requested_by, task_id, release_id=None, metadata=None):
        self.deployments[deployment_id] = {
            "id": deployment_id,
            "agent_id": agent_id,
            "hostname": hostname,
            "release_id": release_id,
            "requested_by": requested_by,
            "task_id": task_id,
            "status": "queued",
            "metadata": metadata or {},
        }

    async def update_deployment(self, deployment_id, **kwargs):
        self.deployments[deployment_id].update(kwargs)

    async def get_deployment(self, deployment_id):
        return self.deployments.get(deployment_id)

    async def get_release(self, release_id):
        return self.releases.get(release_id)

    async def get_latest_release(self):
        return self.releases["release-1"]

    async def get_releases(self, limit=20):
        return list(self.releases.values())[:limit]

    async def upsert_release_from_source(self, **kwargs):
        release_id = kwargs.get("release_id") or "release-1"
        release = {
            "id": release_id,
            "version": kwargs["version"],
            "tag_name": kwargs.get("tag_name") or "",
            "commit_sha": kwargs["commit_sha"],
            "artifact_url": kwargs["artifact_url"],
            "artifact_sha256": kwargs["artifact_sha256"],
            "workflow_run_id": kwargs.get("workflow_run_id"),
            "published_at": kwargs.get("published_at"),
            "metadata": kwargs.get("metadata") or {},
        }
        self.releases[release_id] = release
        return release


class FakeTaskDB:
    def append_log(self, task_id, stream, content, seq):
        return None


class FakeTaskService:
    def __init__(self, dispatch_result):
        self.dispatch_result = dispatch_result
        self.submissions = []

    async def create_and_dispatch(self, task_spec, *, actor="server"):
        self.submissions.append((task_spec, actor))
        return TaskSubmissionResult(
            task={"id": task_spec.id, "status": self.dispatch_result.status},
            dispatch=self.dispatch_result,
        )


class DeploymentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_db = FakeRegistryDB()
        self.task_db = FakeTaskDB()
        self.service = DeploymentService(self.registry_db, self.task_db, Path(self.temp_dir.name))

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_prepare_deployment_marks_failed_when_dispatch_rejected(self):
        self.service.set_task_service(
            FakeTaskService(TaskDispatchResult(accepted=False, status="failed", error="dispatcher unavailable"))
        )

        with patch(
            "vm_agent_server.src.services.deployment_service.provision_guacamole_agent_target_with_diagnostics",
            return_value=(
                {
                    "group_name": "agent-1",
                    "connection_name": "vm-01",
                    "target_host": "192.168.1.50",
                    "username": "operator",
                    "domain": "DESKTOP-JJULF7D",
                },
                {
                    "enabled": True,
                    "data_source": "mysql",
                    "group": {"action": "created", "identifier": "grp-1", "name": "agent-1"},
                    "connection": {"action": "created", "identifier": "conn-1", "name": "vm-01"},
                    "detail": "",
                },
            ),
        ):
            deployment = await self.service.prepare_deployment(
                agent_id="agent-1",
                hostname="vm-01",
                display_name="VM 01",
                guacamole_target_host="192.168.1.50",
                guacamole_username="operator",
                guacamole_domain="DESKTOP-JJULF7D",
                guacamole_password="rdp-pass",
                guacamole_secret="vault-ref",
                guacamole_group_name="agent-1",
                guacamole_connection_name="vm-01",
                release_id="release-1",
                requested_by="operator",
                server_ws_url="ws://localhost:8765/ws",
            )

        self.assertEqual(deployment["status"], "failed")
        self.assertEqual(deployment["error"], "dispatcher unavailable")
        self.assertTrue(self.registry_db.agent_updates)
        self.assertEqual(self.registry_db.agent_updates[-1][0], "agent-1")
        self.assertEqual(self.registry_db.agent_updates[-1][1]["status"], "deploy_failed")
        first_update = self.registry_db.agent_updates[0][1]
        self.assertEqual(first_update["metadata"]["guacamole"]["group_name"], "agent-1")
        self.assertEqual(first_update["metadata"]["guacamole"]["connection_name"], "vm-01")
        self.assertEqual(first_update["metadata"]["guacamole"]["target_host"], "192.168.1.50")
        self.assertEqual(first_update["metadata"]["guacamole"]["username"], "operator")
        self.assertEqual(first_update["metadata"]["guacamole"]["domain"], "DESKTOP-JJULF7D")
        self.assertEqual(self.registry_db.deployments[deployment["id"]]["metadata"]["guacamole_provisioning"]["connection"]["action"], "created")
        self.assertEqual(self.registry_db.deployments[deployment["id"]]["release_id"], "release-1")

    async def test_get_release_artifact_proxy_downloads_and_reuses_cached_file(self):
        artifact_bytes = b"release-binary"
        checksum = "7596d7bc3afde5a1a0ddf7406af03bd0e60344f9728f8f3924d5785cc7e949a9"
        self.registry_db.releases["release-1"]["artifact_sha256"] = checksum
        self.registry_db.releases["release-1"]["metadata"] = {"asset_name": "agent_service.exe"}

        with patch.object(self.service, "_download_release_artifact", return_value=checksum) as download_mock, patch.object(
            self.service,
            "_hash_file_sha256",
            return_value=checksum,
        ):
            cache_dir = Path(self.temp_dir.name) / "artifacts" / "release-proxy" / "release-1"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_path = cache_dir / "agent_service.exe"

            def fake_download(url, destination, task_id=None):
                destination.write_bytes(artifact_bytes)
                return checksum

            download_mock.side_effect = fake_download
            first_path, first_name = await self.service.get_release_artifact_proxy("release-1")
            second_path, second_name = await self.service.get_release_artifact_proxy("release-1")

        self.assertEqual(first_name, "agent_service.exe")
        self.assertEqual(second_name, "agent_service.exe")
        self.assertEqual(first_path, second_path)
        self.assertEqual(first_path.read_bytes(), artifact_bytes)
        self.assertEqual(download_mock.call_count, 1)

    async def test_recover_interrupted_deployments_marks_active_rows_failed(self):
        self.registry_db.deployments = {
            "dep-queued": {
                "id": "dep-queued",
                "agent_id": "agent-queued",
                "hostname": "vm-queued",
                "status": "queued",
            },
            "dep-building": {
                "id": "dep-building",
                "agent_id": "agent-building",
                "hostname": "vm-building",
                "status": "building",
            },
            "dep-ready": {
                "id": "dep-ready",
                "agent_id": "agent-ready",
                "hostname": "vm-ready",
                "status": "ready",
            },
        }

        recovered = await self.service.recover_interrupted_deployments()

        self.assertEqual(recovered, 2)
        self.assertEqual(self.registry_db.deployments["dep-queued"]["status"], "failed")
        self.assertEqual(self.registry_db.deployments["dep-building"]["status"], "failed")
        self.assertEqual(self.registry_db.deployments["dep-ready"]["status"], "ready")
        self.assertIn("interrupted", self.registry_db.deployments["dep-queued"]["error"])
        self.assertEqual(
            [agent_id for agent_id, _ in self.registry_db.agent_updates],
            ["agent-queued", "agent-building"],
        )


if __name__ == "__main__":
    unittest.main()