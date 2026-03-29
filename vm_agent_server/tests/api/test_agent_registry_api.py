import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vm_agent_server.src import server as server_module


class FakeRegistryDB:
    def __init__(self, rotate_result):
        self.rotate_result = rotate_result
        self.rotated_agent_id = None

    async def rotate_agent_token_version(self, agent_id: str):
        self.rotated_agent_id = agent_id
        return self.rotate_result


class AgentRegistryApiTests(unittest.TestCase):
    def setUp(self):
        self.original_registry_db = server_module.registry_db

    def tearDown(self):
        server_module.registry_db = self.original_registry_db

    def test_rotate_token_returns_response_model_payload(self):
        fake_registry = FakeRegistryDB({"agent_id": "agent-7", "token_version": 3, "rotated_at": 1700000000})
        server_module.registry_db = fake_registry

        app = FastAPI()

        @app.middleware("http")
        async def inject_admin_session(request, call_next):
            request.state.user_session = SimpleNamespace(user=SimpleNamespace(roles=["admin"]))
            return await call_next(request)

        app.post("/api/agent-registry/{agent_id}/rotate-token")(server_module.api_rotate_agent_token)
        client = TestClient(app)

        response = client.post("/api/agent-registry/agent-7/rotate-token")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "agent_id": "agent-7", "token_version": 3, "rotated_at": 1700000000})
        self.assertEqual(fake_registry.rotated_agent_id, "agent-7")


if __name__ == "__main__":
    unittest.main()