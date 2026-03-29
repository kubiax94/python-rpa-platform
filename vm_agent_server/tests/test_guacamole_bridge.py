import unittest
from unittest.mock import patch

from vm_agent_server.src.guacamole_bridge import build_guacamole_session, provision_guacamole_agent_target_with_diagnostics


class GuacamoleBridgeTests(unittest.TestCase):
    def test_build_session_uses_agent_record_mapping_when_runtime_metrics_are_missing(self):
        session = build_guacamole_session(
            "agent-1",
            {
                "__agent_record": {
                    "hostname": "vm-01",
                    "display_name": "VM 01",
                    "metadata": {
                        "guacamole": {
                            "group_name": "agent-1",
                            "connection_name": "vm-01",
                            "target_host": "192.168.1.50",
                            "username": "operator",
                            "domain": "DESKTOP-JJULF7D",
                        }
                    },
                }
            },
        )

        self.assertEqual(session["resolved_fields"]["guacamole_group"], "agent-1")
        self.assertEqual(session["resolved_fields"]["guacamole_connection_name"], "vm-01")
        self.assertEqual(session["resolved_fields"]["guacamole_target_host"], "192.168.1.50")
        self.assertEqual(session["resolved_fields"]["guacamole_username"], "operator")
        self.assertEqual(session["resolved_fields"]["guacamole_domain"], "DESKTOP-JJULF7D")
        self.assertEqual(session["guacamole_mapping"]["mapping_strategy"], "agent_group")

    def test_build_session_prefers_active_session_username_for_group_name(self):
        session = build_guacamole_session(
            "agent-1",
            {
                "__agent_metrics": {"hostname": "vm-01"},
                "session:2": {
                    "session_id": 2,
                    "username": "DOMAIN\\alice",
                    "status": "Active",
                    "type": "user_session",
                    "processes": {},
                },
            },
        )

        self.assertEqual(session["resolved_fields"]["guacamole_group"], "DOMAIN\\alice")
        self.assertEqual(session["resolved_fields"]["guacamole_connection_name"], "vm-01")
        self.assertEqual(session["resolved_fields"]["guacamole_username"], "DOMAIN\\alice")

    def test_provision_agent_target_creates_group_and_connection(self):
        mapping = {
            "group_name": "agent-1",
            "group_candidates": ["agent-1"],
            "connection_name": "vm-01",
            "connection_candidates": ["vm-01"],
            "target_host": "192.168.1.50",
            "username": "operator",
            "domain": "DESKTOP-JJULF7D",
        }

        with (
            patch("vm_agent_server.src.guacamole_bridge.get_guacamole_config", return_value={"enabled": True, "request_base_url": "http://guac/guacamole"}),
            patch("vm_agent_server.src.guacamole_bridge._get_auth_config", return_value={"username": "guac-admin", "password": "secret", "provider": "mysql", "connection_type": "c"}),
            patch("vm_agent_server.src.guacamole_bridge._get_provisioning_config", return_value={
                "enabled": True,
                "group_parent_identifier": "ROOT",
                "protocol": "rdp",
                "rdp_port": "3389",
                "parameter_template_json": "",
                "attribute_template_json": "",
                "default_password": "",
                "default_secret": "",
            }),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_token", return_value={"authToken": "auth-token", "dataSource": "mysql"}),
            patch("vm_agent_server.src.guacamole_bridge._resolve_connection_group_identifier", return_value=("", "")),
            patch("vm_agent_server.src.guacamole_bridge._resolve_connection_identifier", return_value=("", "")),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_json_with_body", side_effect=[{"identifier": "grp-1"}, {"identifier": "conn-1"}]) as request_with_body,
        ):
            provisioned, diagnostics = provision_guacamole_agent_target_with_diagnostics(
                "agent-1",
                "vm-01",
                mapping,
                template_values={"password": "rdp-pass", "secret": "vault-ref"},
            )

        self.assertEqual(provisioned["group_identifier"], "grp-1")
        self.assertEqual(provisioned["connection_identifier"], "conn-1")
        self.assertIn("conn-1", provisioned["connection_candidates"])
        self.assertIn("agent-1", provisioned["group_candidates"])
        self.assertEqual(diagnostics["group"]["action"], "created")
        self.assertEqual(diagnostics["connection"]["action"], "created")
        connection_payload = request_with_body.call_args_list[1].args[4]
        self.assertEqual(connection_payload["parameters"]["ignore-cert"], "true")
        self.assertEqual(connection_payload["parameters"]["hostname"], "192.168.1.50")
        self.assertEqual(connection_payload["parameters"]["username"], "operator")
        self.assertEqual(connection_payload["parameters"]["domain"], "DESKTOP-JJULF7D")

    def test_provision_agent_target_splits_legacy_domain_username(self):
        mapping = {
            "group_name": "agent-1",
            "group_candidates": ["agent-1"],
            "connection_name": "vm-01",
            "connection_candidates": ["vm-01"],
            "target_host": "192.168.1.50",
            "username": "DESKTOP-JJULF7D\\jonko",
        }

        with (
            patch("vm_agent_server.src.guacamole_bridge.get_guacamole_config", return_value={"enabled": True, "request_base_url": "http://guac/guacamole"}),
            patch("vm_agent_server.src.guacamole_bridge._get_auth_config", return_value={"username": "guac-admin", "password": "secret", "provider": "mysql", "connection_type": "c"}),
            patch("vm_agent_server.src.guacamole_bridge._get_provisioning_config", return_value={
                "enabled": True,
                "group_parent_identifier": "ROOT",
                "protocol": "rdp",
                "rdp_port": "3389",
                "parameter_template_json": "",
                "attribute_template_json": "",
                "default_password": "",
                "default_secret": "",
            }),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_token", return_value={"authToken": "auth-token", "dataSource": "mysql"}),
            patch("vm_agent_server.src.guacamole_bridge._resolve_connection_group_identifier", return_value=("", "")),
            patch("vm_agent_server.src.guacamole_bridge._resolve_connection_identifier", return_value=("", "")),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_json_with_body", side_effect=[{"identifier": "grp-1"}, {"identifier": "conn-1"}]) as request_with_body,
        ):
            provision_guacamole_agent_target_with_diagnostics(
                "agent-1",
                "vm-01",
                mapping,
            )

        connection_payload = request_with_body.call_args_list[1].args[4]
        self.assertEqual(connection_payload["parameters"]["username"], "jonko")
        self.assertEqual(connection_payload["parameters"]["domain"], "DESKTOP-JJULF7D")

    def test_provision_agent_target_reuses_existing_connection_when_payload_matches(self):
        mapping = {
            "group_name": "agent-1",
            "group_candidates": ["agent-1"],
            "connection_name": "vm-01",
            "connection_candidates": ["vm-01"],
            "group_identifier": "grp-1",
            "connection_identifier": "conn-1",
            "username": "operator",
            "domain": "DESKTOP-JJULF7D",
        }

        with (
            patch("vm_agent_server.src.guacamole_bridge.get_guacamole_config", return_value={"enabled": True, "request_base_url": "http://guac/guacamole"}),
            patch("vm_agent_server.src.guacamole_bridge._get_auth_config", return_value={"username": "guac-admin", "password": "secret", "provider": "mysql", "connection_type": "c"}),
            patch("vm_agent_server.src.guacamole_bridge._get_provisioning_config", return_value={
                "enabled": True,
                "group_parent_identifier": "ROOT",
                "protocol": "rdp",
                "rdp_port": "3389",
                "parameter_template_json": '{"password":"{password}","gateway":"gw"}',
                "attribute_template_json": "",
                "default_password": "",
                "default_secret": "",
            }),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_token", return_value={"authToken": "auth-token", "dataSource": "mysql"}),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_connection_group", return_value={"identifier": "grp-1", "name": "agent-1", "type": "ORGANIZATIONAL", "parentIdentifier": "ROOT", "attributes": {}}),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_connection", return_value={"identifier": "conn-1", "name": "vm-01", "protocol": "rdp", "parentIdentifier": "grp-1", "attributes": {}}),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_connection_parameters", return_value={"hostname": "vm-01", "port": "3389", "resize-method": "display-update", "ignore-cert": "true", "username": "operator", "domain": "DESKTOP-JJULF7D", "password": "rdp-pass", "gateway": "gw"}),
            patch("vm_agent_server.src.guacamole_bridge._request_guacamole_json_with_body") as request_with_body,
        ):
            _, diagnostics = provision_guacamole_agent_target_with_diagnostics(
                "agent-1",
                "vm-01",
                mapping,
                template_values={"password": "rdp-pass"},
            )

        request_with_body.assert_not_called()
        self.assertEqual(diagnostics["group"]["action"], "reused")
        self.assertEqual(diagnostics["connection"]["action"], "reused")


if __name__ == "__main__":
    unittest.main()