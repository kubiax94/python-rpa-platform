import asyncio
import unittest
from unittest.mock import patch

from vm_agent_server.src.services.guacamole_service import GuacamoleService, GuacamoleTunnelStreamResponse
from vm_agent_server.src.services.rdp_monitor_service import RdpMonitorService


class GuacamoleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_client_session_registers_rdp_monitor_state(self):
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": f"{base_url}/api/guacamole/tunnel", "websocket": f"{base_url}/api/guacamole/websocket-tunnel"},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {"agent_id": agent_id, "state": state},
            inspect_guacamole_connection=lambda agent_id, state: {"agent_id": agent_id, "state": state},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {
                "status": "ready",
                "client_session": {
                    "auth_token": "auth-1",
                    "data_source": "mysql",
                    "connection_id": "conn-1",
                    "connection_type": "c",
                    "display": {"mode": "dynamic", "dpi": 96},
                    "tunnels": tunnels,
                },
            },
            invalidate_guacamole_token=lambda base_url, auth_token: True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        session = await service.create_client_session("agent-1", {"ok": True}, "http://server")

        self.assertEqual(session["client_session"]["auth_token"], "auth-1")
        snapshot = monitor.build_snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["agent_id"], "agent-1")
        self.assertEqual(snapshot[0]["connection_id"], "conn-1")

    async def test_expire_idle_sessions_invalidates_and_forgets_tokens(self):
        invalidated_tokens: list[str] = []
        monitor = RdpMonitorService(idle_timeout_seconds=1)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": "", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: invalidated_tokens.append(auth_token) or True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")
        tracked_session = monitor._sessions_by_token["auth-1"]
        tracked_session.last_activity_at -= 10

        expired_count = await service.expire_idle_sessions()

        self.assertEqual(expired_count, 1)
        self.assertEqual(invalidated_tokens, ["auth-1"])
        self.assertEqual(monitor.build_snapshot(), [])

    async def test_list_tracked_sessions_returns_latest_activity_first(self):
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": "", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")
        monitor.register_session(agent_id="agent-2", auth_token="auth-2", connection_id="conn-2", data_source="mysql")
        monitor._sessions_by_token["auth-1"].last_activity_at -= 10

        tracked = service.list_tracked_sessions()

        self.assertEqual(tracked["tracked_count"], 2)
        self.assertEqual(tracked["sessions"][0]["agent_id"], "agent-2")
        self.assertEqual(tracked["sessions"][1]["agent_id"], "agent-1")

    async def test_close_tracked_sessions_invalidates_everything(self):
        invalidated_tokens: list[str] = []
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": "", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: invalidated_tokens.append(auth_token) or True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")
        monitor.register_session(agent_id="agent-2", auth_token="auth-2", connection_id="conn-2", data_source="mysql")

        closed_count = await service.close_tracked_sessions(close_reason="Operator terminated")

        self.assertEqual(closed_count, 2)
        self.assertEqual(invalidated_tokens, ["auth-1", "auth-2"])
        self.assertEqual(monitor.build_snapshot(), [])

    async def test_schedule_session_close_closes_after_delay(self):
        invalidated_tokens: list[str] = []
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": "", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: invalidated_tokens.append(auth_token) or True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")

        scheduled = service.schedule_session_close("auth-1", delay_seconds=0.5)

        self.assertTrue(scheduled)
        await asyncio.sleep(0.7)
        self.assertEqual(invalidated_tokens, ["auth-1"])
        self.assertEqual(monitor.build_snapshot(), [])

    async def test_create_client_session_cancels_scheduled_close_for_refresh_reclaim(self):
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": f"{base_url}/api/guacamole/tunnel", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {"display": {"mode": "dynamic", "dpi": 96}},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")
        service.schedule_session_close("auth-1", delay_seconds=5)

        with patch.object(service, "_open_http_tunnel", return_value="tunnel-fresh"):
            session = await service.create_client_session("agent-1", {"ok": True}, "http://server")

        self.assertEqual(session["client_session"]["auth_token"], "auth-1")
        self.assertFalse(service._pending_close_tasks)

    async def test_proxy_tunnel_get_uses_shutdown_safe_streaming_response(self):
        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": "", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
        )

        class FakeResponse:
            status = 200

            def __init__(self):
                self.headers = {"Content-Type": "application/octet-stream"}
                self._chunks = [b"abc", b""]
                self.closed = False

            def read(self, size=-1):
                return self._chunks.pop(0)

            def close(self):
                self.closed = True

        upstream_response = FakeResponse()

        with patch("vm_agent_server.src.services.guacamole_service.urlopen", return_value=upstream_response):
            response = service.proxy_tunnel_request("GET", "read:tunnel-1", b"", {"accept": "*/*"})

        self.assertIsInstance(response, GuacamoleTunnelStreamResponse)

        sent_messages: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await response(
            {"type": "http", "asgi": {"spec_version": "2.3"}, "method": "GET", "path": "/api/guacamole/tunnel"},
            receive,
            send,
        )

        self.assertEqual(sent_messages[0]["type"], "http.response.start")
        self.assertEqual(sent_messages[1]["body"], b"abc")
        self.assertTrue(sent_messages[1]["more_body"])
        self.assertEqual(sent_messages[2]["body"], b"")
        self.assertFalse(sent_messages[2]["more_body"])
        self.assertTrue(upstream_response.closed)

    async def test_create_client_session_force_fresh_invalidates_existing_session(self):
        invalidated_tokens: list[str] = []
        created_sessions: list[str] = []
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": f"{base_url}/api/guacamole/tunnel", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {"display": {"mode": "dynamic", "dpi": 96}},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: created_sessions.append(agent_id) or {
                "status": "ready",
                "client_session": {
                    "auth_token": "auth-2",
                    "data_source": "mysql",
                    "connection_id": "conn-2",
                    "connection_type": "c",
                    "display": {"mode": "dynamic", "dpi": 96},
                    "tunnels": tunnels,
                },
            },
            invalidate_guacamole_token=lambda base_url, auth_token: invalidated_tokens.append(auth_token) or True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")

        session = await service.create_client_session("agent-1", {"ok": True}, "http://server", force_fresh=True)

        self.assertEqual(invalidated_tokens, ["auth-1"])
        self.assertEqual(created_sessions, ["agent-1"])
        self.assertEqual(session["client_session"]["auth_token"], "auth-2")

    async def test_create_client_session_reuses_existing_token_with_existing_resume_tunnel(self):
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": f"{base_url}/api/guacamole/tunnel", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {"display": {"mode": "dynamic", "dpi": 96}},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")
        monitor.bind_tunnel("auth-1", "tunnel-existing")
        with patch.object(service, "_open_http_tunnel", return_value="tunnel-fresh") as open_tunnel:
            session = await service.create_client_session("agent-1", {"ok": True}, "http://server")

        self.assertEqual(session["client_session"]["auth_token"], "auth-1")
        self.assertEqual(session["client_session"]["resume_tunnel_uuid"], "tunnel-existing")
        open_tunnel.assert_not_called()

    async def test_create_client_session_reuses_existing_token_and_opens_tunnel_only_when_missing(self):
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": f"{base_url}/api/guacamole/tunnel", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {"display": {"mode": "dynamic", "dpi": 96}},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")
        with patch.object(service, "_open_http_tunnel", return_value="tunnel-fresh") as open_tunnel:
            session = await service.create_client_session("agent-1", {"ok": True}, "http://server")

        self.assertEqual(session["client_session"]["auth_token"], "auth-1")
        self.assertEqual(session["client_session"]["resume_tunnel_uuid"], "tunnel-fresh")
        open_tunnel.assert_called_once()

    async def test_create_client_session_refresh_tunnel_keeps_auth_and_opens_new_tunnel(self):
        monitor = RdpMonitorService(idle_timeout_seconds=60)

        service = GuacamoleService(
            build_proxy_tunnel_urls=lambda base_url: {"http": f"{base_url}/api/guacamole/tunnel", "websocket": ""},
            get_guacamole_config=lambda: {"enabled": True, "request_base_url": "http://guac/guacamole"},
            list_guacamole_connections=lambda: [],
            build_guacamole_session=lambda agent_id, state: {"display": {"mode": "dynamic", "dpi": 96}},
            inspect_guacamole_connection=lambda agent_id, state: {},
            create_guacamole_client_session=lambda agent_id, state, tunnels: {"client_session": None},
            invalidate_guacamole_token=lambda base_url, auth_token: True,
            get_guacamole_base_url=lambda: "http://guac/guacamole",
            rdp_monitor=monitor,
        )

        monitor.register_session(agent_id="agent-1", auth_token="auth-1", connection_id="conn-1", data_source="mysql")
        monitor.bind_tunnel("auth-1", "tunnel-existing")
        with patch.object(service, "_open_http_tunnel", return_value="tunnel-fresh") as open_tunnel:
            session = await service.create_client_session("agent-1", {"ok": True}, "http://server", refresh_tunnel=True)

        self.assertEqual(session["client_session"]["auth_token"], "auth-1")
        self.assertEqual(session["client_session"]["resume_tunnel_uuid"], "tunnel-fresh")
        open_tunnel.assert_called_once()


if __name__ == "__main__":
    unittest.main()