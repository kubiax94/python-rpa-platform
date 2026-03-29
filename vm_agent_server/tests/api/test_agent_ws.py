import os
import tempfile
import time
import unittest
import asyncio
import threading
from unittest.mock import patch

from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from shared.network.events.example_event import AuthResultEvent, HandshakeData, HandshakeEvent
from shared.security.agent_jwt import looks_like_jwt
from vm_agent_server.src.persistence.agent_registry_db import AgentRegistryDB, hash_token
from vm_agent_server.src.agent_auth import issue_agent_access_token
from vm_agent_server.src import server as server_module


class FakeSnapshotEvent:
    def __init__(self):
        self.set_calls = 0

    def set(self):
        self.set_calls += 1


class FakeRegistryDB:
    def __init__(self, auth_result):
        self.auth_result = auth_result
        self.upsert_calls = []

    async def authorize_agent(self, agent_id, token):
        return self.auth_result(agent_id, token) if callable(self.auth_result) else self.auth_result

    async def get_latest_deployment_for_agent(self, agent_id):
        return None

    async def update_deployment(self, deployment_id, **kwargs):
        return None

    async def upsert_agent(self, agent_id, **kwargs):
        self.upsert_calls.append((agent_id, kwargs))

    async def get_expected_hostname_for_agent(self, agent_id):
        return ""


class FakeAgentRuntime:
    def __init__(self):
        self.register_calls = []
        self.unregister_calls = []

    async def register_agent(self, agent_id, ws):
        self.register_calls.append(agent_id)

    async def unregister_agent(self, agent_id, ws=None):
        self.unregister_calls.append(agent_id)
        return True

    def merge_heartbeat(self, payload, telemetry_db):
        return None


class ThreadedRegistryDB:
    def __init__(self, db_path):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._db = AgentRegistryDB(db_path=db_path)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self):
        self._thread.start()
        self.run_sync(self._db.start())

    def stop(self):
        try:
            self.run_sync(self._db.stop())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            self._loop.close()

    def run_sync(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=5)

    async def _run_async(self, coro):
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, self._loop))

    async def authorize_agent(self, agent_id, token):
        return await self._run_async(self._db.authorize_agent(agent_id, token))

    async def get_latest_deployment_for_agent(self, agent_id):
        return await self._run_async(self._db.get_latest_deployment_for_agent(agent_id))

    async def update_deployment(self, deployment_id, **kwargs):
        return await self._run_async(self._db.update_deployment(deployment_id, **kwargs))

    async def upsert_agent(self, agent_id, **kwargs):
        return await self._run_async(self._db.upsert_agent(agent_id, **kwargs))

    async def set_bootstrap_token(self, agent_id, token_hash, expires_at):
        return await self._run_async(self._db.set_bootstrap_token(agent_id, token_hash, expires_at))

    async def get_expected_hostname_for_agent(self, agent_id):
        return await self._run_async(self._db.get_expected_hostname_for_agent(agent_id))


class AgentWebSocketHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "registry_db": server_module.registry_db,
            "agent_runtime": server_module.agent_runtime,
            "frontend_snapshot_event": server_module.frontend_snapshot_event,
            "process_manager_watchers": server_module.process_manager_watchers,
            "frontend_clients": server_module.frontend_clients,
        }
        self.temp_dir = None
        self.registry_db = None
        self.client = None

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(server_module, name, value)
        if self.client is not None:
            self.client.close()
            self.client = None
        if self.registry_db is not None:
            self.registry_db.stop()
            self.registry_db = None
        if self.temp_dir is not None:
            self.temp_dir.cleanup()

    def _build_client(self, auth_result):
        server_module.registry_db = FakeRegistryDB(auth_result)
        server_module.agent_runtime = FakeAgentRuntime()
        server_module.frontend_snapshot_event = FakeSnapshotEvent()
        server_module.process_manager_watchers = {}
        server_module.frontend_clients = set()

        app = FastAPI()
        app.websocket("/ws")(server_module.websocket_endpoint)
        self.client = TestClient(app)
        return self.client

    def test_ws_handshake_bootstrap_returns_runtime_jwt(self):
        def auth_result(agent_id, token):
            return {
                "authorized": True,
                "mode": "bootstrap",
                "issued_secret": issue_agent_access_token(agent_id, token_version=1),
            }

        client = self._build_client(auth_result)

        with client.websocket_connect("/ws", headers={"Authorization": "Bearer bootstrap-token"}) as ws:
            server_handshake = ws.receive_text()
            self.assertIn('"type":"handshake"', server_handshake)

            ws.send_text(HandshakeEvent(data=HandshakeData(client_id="agent-1", hostname="vm-1")).model_dump_json())
            auth_response = AuthResultEvent.model_validate_json(ws.receive_text())

            self.assertEqual(auth_response.data.status, "ok")
            self.assertEqual(auth_response.data.agent_id, "agent-1")
            self.assertTrue(auth_response.data.access_token_issued)
            self.assertTrue(looks_like_jwt(auth_response.data.access_token))

        self.assertEqual(server_module.agent_runtime.register_calls, ["agent-1"])
        self.assertGreaterEqual(server_module.frontend_snapshot_event.set_calls, 1)

    def test_ws_handshake_rejects_unauthorized_agent(self):
        client = self._build_client({"authorized": False, "reason": "invalid bearer token"})

        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"Authorization": "Bearer bad-token"}) as ws:
                ws.receive_text()
                ws.send_text(HandshakeEvent(data=HandshakeData(client_id="agent-bad", hostname="vm-bad")).model_dump_json())
                auth_response = AuthResultEvent.model_validate_json(ws.receive_text())
                self.assertEqual(auth_response.data.status, "error")
                self.assertEqual(auth_response.data.reason, "invalid bearer token")
                ws.receive_text()

    def test_ws_handshake_bootstrap_reconnect_recovery_rejects_old_jwt(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_db = ThreadedRegistryDB(db_path=os.path.join(self.temp_dir.name, "agents-ws.db"))
        with patch.dict(
            os.environ,
            {
                "VM_AGENT_JWT_SECRET": "jwt-test-secret",
                "VM_AGENT_JWT_ISSUER": "jwt-test-issuer",
            },
            clear=False,
        ):
            self.registry_db.start()
            self.registry_db.run_sync(self.registry_db.upsert_agent("agent-flow"))
            self.registry_db.run_sync(
                self.registry_db.set_bootstrap_token(
                    "agent-flow",
                    hash_token("bootstrap-token"),
                    int(time.time()) + 60,
                )
            )

            server_module.registry_db = self.registry_db
            server_module.agent_runtime = FakeAgentRuntime()
            server_module.frontend_snapshot_event = FakeSnapshotEvent()
            server_module.process_manager_watchers = {}
            server_module.frontend_clients = set()

            app = FastAPI()
            app.websocket("/ws")(server_module.websocket_endpoint)
            self.client = TestClient(app)
            client = self.client

            with client.websocket_connect("/ws", headers={"Authorization": "Bearer bootstrap-token"}) as ws:
                ws.receive_text()
                ws.send_text(HandshakeEvent(data=HandshakeData(client_id="agent-flow", hostname="vm-1")).model_dump_json())
                first_auth = AuthResultEvent.model_validate_json(ws.receive_text())

            first_token = first_auth.data.access_token
            self.assertTrue(first_auth.data.access_token_issued)
            self.assertTrue(looks_like_jwt(first_token))

            with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {first_token}"}) as ws:
                ws.receive_text()
                ws.send_text(HandshakeEvent(data=HandshakeData(client_id="agent-flow", hostname="vm-1")).model_dump_json())
                reconnect_auth = AuthResultEvent.model_validate_json(ws.receive_text())

            self.assertEqual(reconnect_auth.data.status, "ok")
            self.assertFalse(reconnect_auth.data.access_token_issued)
            self.assertEqual(reconnect_auth.data.access_token, "")

            with client.websocket_connect("/ws", headers={"Authorization": "Bearer bootstrap-token"}) as ws:
                ws.receive_text()
                ws.send_text(HandshakeEvent(data=HandshakeData(client_id="agent-flow", hostname="vm-1")).model_dump_json())
                recovery_auth = AuthResultEvent.model_validate_json(ws.receive_text())

            second_token = recovery_auth.data.access_token
            self.assertEqual(recovery_auth.data.status, "ok")
            self.assertTrue(recovery_auth.data.access_token_issued)
            self.assertNotEqual(second_token, first_token)

            with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {first_token}"}) as ws:
                ws.receive_text()
                ws.send_text(HandshakeEvent(data=HandshakeData(client_id="agent-flow", hostname="vm-1")).model_dump_json())
                rejected_auth = AuthResultEvent.model_validate_json(ws.receive_text())
                self.assertEqual(rejected_auth.data.status, "error")
                self.assertEqual(rejected_auth.data.reason, "invalid bearer token")
                with self.assertRaises(WebSocketDisconnect):
                    ws.receive_text()