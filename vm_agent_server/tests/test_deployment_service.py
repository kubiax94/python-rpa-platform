import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vm_agent_server.src.deployment_service import DeploymentService
from vm_agent_server.src.task_dispatcher import TaskDispatchResult
from vm_agent_server.src.task_service import TaskSubmissionResult


class FakeRegistryDB:
    def __init__(self):
        self.deployments = {}
        self.agent_updates = []
        self.bootstrap_tokens = []

    async def get_active_deployment(self):
        for deployment in self.deployments.values():
            if deployment["status"] in {"queued", "building"}:
                return deployment
        return None

    async def get_active_deployments(self):
        return [deployment for deployment in self.deployments.values() if deployment["status"] in {"queued", "building"}]

    async def upsert_agent(self, agent_id, **kwargs):
        self.agent_updates.append((agent_id, kwargs))

    async def set_bootstrap_token(self, agent_id, token_hash, expires_at):
        self.bootstrap_tokens.append((agent_id, token_hash, expires_at))

    async def create_deployment(self, deployment_id, agent_id, hostname, repo_url, source_ref, requested_by, task_id, metadata=None):
        self.deployments[deployment_id] = {
            "id": deployment_id,
            "agent_id": agent_id,
            "hostname": hostname,
            "repo_url": repo_url,
            "source_ref": source_ref,
            "requested_by": requested_by,
            "task_id": task_id,
            "status": "queued",
            "metadata": metadata or {},
        }

    async def update_deployment(self, deployment_id, **kwargs):
        self.deployments[deployment_id].update(kwargs)

    async def get_deployment(self, deployment_id):
        return self.deployments.get(deployment_id)


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
            "vm_agent_server.src.deployment_service.provision_guacamole_agent_target_with_diagnostics",
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
                repo_url="https://example.test/repo.git",
                source_ref="main",
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