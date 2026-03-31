from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import WebSocket

from shared.network.events.example_event import AuthResultData, AuthResultEvent, HeartbeatEvent, HandshakeEvent
from shared.protocol.network_event import NetworkEvent
from vm_agent_server.src.network.context import AgentConnectionState, AgentLifecycleContext

logger = logging.getLogger(__name__)


class AgentLifecycleEventHandler:
    event_types = ("handshake", "heartbeat")

    def __init__(
        self,
        registry_db: Any,
        agent_runtime: Any,
        telemetry_db: Any,
        frontend_snapshot_event: Any,
        process_manager_watchers: dict[str, set[WebSocket]],
    ):
        self._registry_db = registry_db
        self._agent_runtime = agent_runtime
        self._telemetry_db = telemetry_db
        self._frontend_snapshot_event = frontend_snapshot_event
        self._process_manager_watchers = process_manager_watchers

    async def handle(
        self,
        event: NetworkEvent,
        context: AgentLifecycleContext,
    ) -> bool:
        if event.type == "handshake":
            return await self._handle_handshake(event, context)
        if event.type == "heartbeat":
            return await self._handle_heartbeat(event, context)
        return True

    async def cleanup_connection(self, context: AgentLifecycleContext) -> bool:
        if context.state.client_id:
            await self._registry_db.upsert_agent(
                context.state.client_id,
                status="registered",
                connection_status="offline",
                last_seen_at=int(time.time()),
            )
        return await self._agent_runtime.unregister_agent(context.state.client_id, context.ws)

    async def _handle_handshake(
        self,
        event: NetworkEvent,
        context: AgentLifecycleContext,
    ) -> bool:
        if not isinstance(event, HandshakeEvent):
            return True

        requested_client_id = event.data.client_id
        reported_hostname = str(getattr(event.data, "hostname", "") or "").strip()
        auth_result = await self._registry_db.authorize_agent(requested_client_id, context.auth_token)
        if not auth_result.get("authorized"):
            reason = auth_result.get("reason", "unauthorized")
            latest_deployment = await self._registry_db.get_latest_deployment_for_agent(requested_client_id)
            if latest_deployment and reason == "bootstrap token expired":
                await self._registry_db.update_deployment(
                    latest_deployment["id"],
                    status="expired_bootstrap",
                    error="Bootstrap token expired before the first successful agent start.",
                    completed_at=int(time.time()),
                )
                await self._registry_db.upsert_agent(
                    requested_client_id,
                    status="bootstrap_expired",
                    connection_status="offline",
                    last_deployment_id=latest_deployment["id"],
                    last_seen_at=int(time.time()),
                )
            logger.warning("Rejecting agent %s during handshake: %s", requested_client_id, reason)
            await context.ws.send_text(
                AuthResultEvent(
                    data=AuthResultData(status="error", agent_id=requested_client_id, reason=reason)
                ).model_dump_json()
            )
            await context.ws.close(code=4401, reason=reason)
            return False

        expected_hostname = await self._registry_db.get_expected_hostname_for_agent(requested_client_id)
        if expected_hostname and reported_hostname and expected_hostname.lower() != reported_hostname.lower():
            reason = f"hostname mismatch: expected {expected_hostname}, got {reported_hostname}"
            latest_deployment = await self._registry_db.get_latest_deployment_for_agent(requested_client_id)
            if latest_deployment:
                await self._registry_db.update_deployment(
                    latest_deployment["id"],
                    error=f"Agent attempted bootstrap from unexpected host '{reported_hostname}'. Expected '{expected_hostname}'.",
                )
            await self._registry_db.upsert_agent(
                requested_client_id,
                hostname=expected_hostname,
                status="hostname_mismatch",
                connection_status="offline",
                last_seen_at=int(time.time()),
            )
            logger.warning("Rejecting agent %s during handshake: %s", requested_client_id, reason)
            await context.ws.send_text(
                AuthResultEvent(
                    data=AuthResultData(status="error", agent_id=requested_client_id, reason=reason)
                ).model_dump_json()
            )
            await context.ws.close(code=4403, reason="hostname mismatch")
            return False

        context.state.client_id = requested_client_id
        context.state.authenticated = True
        issued_secret = auth_result.get("issued_secret") or ""
        await context.ws.send_text(
            AuthResultEvent(
                data=AuthResultData(
                    status="ok",
                    agent_id=requested_client_id,
                    access_token=issued_secret,
                    access_token_issued=bool(issued_secret),
                )
            ).model_dump_json()
        )
        logger.info("Handshake received from agent %s", requested_client_id)
        await self._agent_runtime.register_agent(requested_client_id, context.ws)
        await self._registry_db.upsert_agent(
            requested_client_id,
            status="registered",
            connection_status="online",
            last_seen_at=int(time.time()),
        )
        if self._process_manager_watchers.get(requested_client_id):
            await context.set_window_tracking(requested_client_id, True)
        self._frontend_snapshot_event.set()
        return True

    async def _handle_heartbeat(
        self,
        event: NetworkEvent,
        context: AgentLifecycleContext,
    ) -> bool:
        if not isinstance(event, HeartbeatEvent):
            return True

        if not context.state.authenticated:
            await context.ws.close(code=4401, reason="handshake required")
            return False

        self._agent_runtime.merge_heartbeat(event.data, self._telemetry_db)
        metrics = event.data.system_metrics if hasattr(event.data, "system_metrics") else {}
        hostname = metrics.get("hostname", "") if isinstance(metrics, dict) else ""
        if context.state.client_id:
            expected_hostname = await self._registry_db.get_expected_hostname_for_agent(context.state.client_id)
            if expected_hostname and hostname and expected_hostname.lower() != hostname.lower():
                logger.warning(
                    "Disconnecting agent %s after heartbeat hostname mismatch: expected %s, got %s",
                    context.state.client_id,
                    expected_hostname,
                    hostname,
                )
                await self._registry_db.upsert_agent(
                    context.state.client_id,
                    hostname=expected_hostname,
                    status="hostname_mismatch",
                    connection_status="offline",
                    last_seen_at=int(time.time()),
                )
                await context.ws.close(code=4403, reason="hostname mismatch")
                return False
        if context.state.client_id:
            await self._registry_db.upsert_agent(
                context.state.client_id,
                hostname=hostname,
                status="active",
                connection_status="online",
                metadata=metrics if isinstance(metrics, dict) else {},
                last_seen_at=int(time.time()),
            )
        self._frontend_snapshot_event.set()
        return True