import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vm_agent_server.src.api.routers.deployment_router import build_deployment_router


class FakeDeploymentService:
    def __init__(self):
        self.prepare_args = None

    def get_default_repo_url(self):
        return "https://example.test/repo.git"

    async def prepare_deployment(self, **kwargs):
        self.prepare_args = kwargs
        return {"id": "dep-1", "status": "queued"}

    async def get_prepare_config(self):
        return {"default_repo_url": self.get_default_repo_url()}


class FakeRegistryDB:
    def __init__(self):
        self.deployment = None

    async def get_active_deployment(self):
        return None

    async def get_deployments(self, agent_id=None, limit=100):
        return []

    async def get_deployment(self, deployment_id):
        return self.deployment


class DeploymentRouterTests(unittest.TestCase):
    def setUp(self):
        self.deployment_service = FakeDeploymentService()
        self.registry_db = FakeRegistryDB()
        app = FastAPI()
        app.include_router(build_deployment_router(self.deployment_service, self.registry_db, lambda request: "ws://localhost:8765/ws"))
        self.client = TestClient(app)

    def test_prepare_deployment_uses_pydantic_validation(self):
        response = self.client.post("/api/deployments/prepare", json={"source_ref": "main"})

        self.assertEqual(response.status_code, 422)

    def test_prepare_deployment_applies_defaults(self):
        response = self.client.post(
            "/api/deployments/prepare",
            json={"hostname": "vm-01", "requested_by": "operator"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.deployment_service.prepare_args["agent_id"], "vm-01")
        self.assertEqual(self.deployment_service.prepare_args["display_name"], "vm-01")
        self.assertEqual(self.deployment_service.prepare_args["repo_url"], "https://example.test/repo.git")
        self.assertEqual(self.deployment_service.prepare_args["source_ref"], "main")
        self.assertEqual(self.deployment_service.prepare_args["server_ws_url"], "ws://localhost:8765/ws")

    def test_get_installer_returns_plain_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installer_path = Path(temp_dir) / "install.ps1"
            installer_path.write_text("Write-Host 'ok'", encoding="utf-8")
            self.registry_db.deployment = {"installer_copy_path": str(installer_path), "install_script_path": ""}

            response = self.client.get("/api/deployments/dep-1/installer")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Write-Host", response.text)


if __name__ == "__main__":
    unittest.main()