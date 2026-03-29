import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vm_agent_server.src.api.routers.deployment_router import build_deployment_router


class FakeDeploymentService:
    def __init__(self):
        self.prepare_args = None
        self.prepare_error = None

    def get_default_repo_url(self):
        return "https://example.test/repo.git"

    async def prepare_deployment(self, **kwargs):
        if self.prepare_error is not None:
            raise self.prepare_error
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
        self.assertEqual(self.deployment_service.prepare_args["guacamole_target_host"], "vm-01")
        self.assertEqual(self.deployment_service.prepare_args["guacamole_group_name"], "vm-01")
        self.assertEqual(self.deployment_service.prepare_args["guacamole_connection_name"], "vm-01")
        self.assertEqual(self.deployment_service.prepare_args["repo_url"], "https://example.test/repo.git")
        self.assertEqual(self.deployment_service.prepare_args["source_ref"], "main")
        self.assertEqual(self.deployment_service.prepare_args["server_ws_url"], "ws://localhost:8765/ws")

    def test_prepare_deployment_forwards_optional_guacamole_username(self):
        response = self.client.post(
            "/api/deployments/prepare",
            json={"hostname": "vm-02", "guacamole_username": "operator"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.deployment_service.prepare_args["guacamole_username"], "operator")

    def test_prepare_deployment_forwards_optional_guacamole_domain(self):
        response = self.client.post(
            "/api/deployments/prepare",
            json={"hostname": "vm-02", "guacamole_domain": "DESKTOP-JJULF7D"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.deployment_service.prepare_args["guacamole_domain"], "DESKTOP-JJULF7D")

    def test_prepare_deployment_forwards_guacamole_target_host(self):
        response = self.client.post(
            "/api/deployments/prepare",
            json={"hostname": "vm-02", "guacamole_target_host": "192.168.1.50"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.deployment_service.prepare_args["guacamole_target_host"], "192.168.1.50")

    def test_prepare_deployment_forwards_secret_template_inputs(self):
        response = self.client.post(
            "/api/deployments/prepare",
            json={"hostname": "vm-02", "guacamole_password": "rdp-pass", "guacamole_secret": "vault-ref"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.deployment_service.prepare_args["guacamole_password"], "rdp-pass")
        self.assertEqual(self.deployment_service.prepare_args["guacamole_secret"], "vault-ref")

    def test_get_installer_returns_plain_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installer_path = Path(temp_dir) / "install.ps1"
            installer_path.write_text("Write-Host 'ok'", encoding="utf-8")
            self.registry_db.deployment = {"installer_copy_path": str(installer_path), "install_script_path": ""}

            response = self.client.get("/api/deployments/dep-1/installer")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Write-Host", response.text)

    def test_get_package_returns_zip_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = Path(temp_dir) / "package.zip"
            package_path.write_bytes(b"PK\x03\x04demo")
            self.registry_db.deployment = {"package_zip_path": str(package_path)}

            response = self.client.get("/api/deployments/dep-1/package")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertIn('attachment; filename="deployment-dep-1.zip"', response.headers.get("content-disposition", ""))

    def test_prepare_deployment_returns_502_for_backend_failure_without_active_deployment(self):
        self.deployment_service.prepare_error = RuntimeError("Guacamole provisioning failed")

        response = self.client.post(
            "/api/deployments/prepare",
            json={"hostname": "vm-03"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "Guacamole provisioning failed")

    def test_get_guacamole_provisioning_diagnostics(self):
        self.registry_db.deployment = {
            "id": "dep-1",
            "agent_id": "agent-1",
            "hostname": "vm-01",
            "metadata": {
                "guacamole_provisioning": {
                    "data_source": "mysql",
                    "group": {"action": "created", "identifier": "grp-1", "name": "agent-1"},
                    "connection": {"action": "reused", "identifier": "conn-1", "name": "vm-01"},
                    "detail": "",
                }
            },
        }

        response = self.client.get("/api/deployments/dep-1/guacamole/provisioning")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])
        self.assertEqual(response.json()["group"]["action"], "created")
        self.assertEqual(response.json()["connection"]["action"], "reused")


if __name__ == "__main__":
    unittest.main()