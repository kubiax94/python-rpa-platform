import os
import tempfile
import time
import unittest
from unittest.mock import patch

from shared.security.agent_jwt import AgentJwtError, TOKEN_PURPOSE_AGENT_WS, issue_agent_jwt, looks_like_jwt, verify_agent_jwt
from vm_agent_server.src.persistence.agent_registry_db import AgentRegistryDB, hash_token


class SharedAgentJwtTests(unittest.TestCase):
    def test_issue_and_verify_round_trip(self):
        token = issue_agent_jwt(
            secret="test-signing-secret",
            agent_id="agent-1",
            issuer="test-issuer",
            ttl_seconds=60,
            now=1_700_000_000,
        )

        claims = verify_agent_jwt(
            token,
            "test-signing-secret",
            expected_agent_id="agent-1",
            expected_version=1,
            expected_purpose=TOKEN_PURPOSE_AGENT_WS,
            expected_issuer="test-issuer",
            now=1_700_000_010,
        )

        self.assertEqual(claims.agent_id, "agent-1")
        self.assertEqual(claims.sub, "agent-1")
        self.assertEqual(claims.iss, "test-issuer")
        self.assertEqual(claims.purpose, TOKEN_PURPOSE_AGENT_WS)
        self.assertTrue(looks_like_jwt(token))

    def test_verify_rejects_tampered_token(self):
        token = issue_agent_jwt(secret="test-signing-secret", agent_id="agent-1", now=1_700_000_000)
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

        with self.assertRaises(AgentJwtError):
            verify_agent_jwt(tampered, "test-signing-secret", expected_agent_id="agent-1")


class AgentRegistryAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "agents-test.db")
        self.registry_db = AgentRegistryDB(db_path=self.db_path)
        await self.registry_db.start()

    async def asyncTearDown(self):
        await self.registry_db.stop()
        self.temp_dir.cleanup()

    async def test_authorize_agent_bootstrap_issues_jwt(self):
        with patch.dict(
            os.environ,
            {
                "VM_AGENT_JWT_SECRET": "jwt-test-secret",
                "VM_AGENT_JWT_ISSUER": "jwt-test-issuer",
            },
            clear=False,
        ):
            await self.registry_db.upsert_agent("agent-1")
            await self.registry_db.set_bootstrap_token("agent-1", hash_token("bootstrap-token"), int(time.time()) + 60)

            result = await self.registry_db.authorize_agent("agent-1", "bootstrap-token")

        self.assertTrue(result["authorized"])
        self.assertEqual(result["mode"], "bootstrap")
        self.assertTrue(looks_like_jwt(result["issued_secret"]))

        claims = verify_agent_jwt(
            result["issued_secret"],
            "jwt-test-secret",
            expected_agent_id="agent-1",
            expected_version=1,
            expected_purpose=TOKEN_PURPOSE_AGENT_WS,
            expected_issuer="jwt-test-issuer",
        )
        self.assertEqual(claims.agent_id, "agent-1")

        credentials = await self.registry_db.get_agent_credentials("agent-1")
        self.assertEqual(credentials["token_version"], 1)
        self.assertIsNone(credentials["secret_hash"])

    async def test_authorize_agent_accepts_issued_jwt(self):
        with patch.dict(
            os.environ,
            {
                "VM_AGENT_JWT_SECRET": "jwt-test-secret",
                "VM_AGENT_JWT_ISSUER": "jwt-test-issuer",
            },
            clear=False,
        ):
            await self.registry_db.upsert_agent("agent-2")
            await self.registry_db.set_bootstrap_token("agent-2", hash_token("bootstrap-token"), int(time.time()) + 60)
            bootstrap_result = await self.registry_db.authorize_agent("agent-2", "bootstrap-token")

            result = await self.registry_db.authorize_agent("agent-2", bootstrap_result["issued_secret"])

        self.assertTrue(result["authorized"])
        self.assertEqual(result["mode"], "jwt")
        self.assertIsNone(result["issued_secret"])

    async def test_authorize_agent_rejects_jwt_for_other_agent(self):
        with patch.dict(
            os.environ,
            {
                "VM_AGENT_JWT_SECRET": "jwt-test-secret",
                "VM_AGENT_JWT_ISSUER": "jwt-test-issuer",
            },
            clear=False,
        ):
            foreign_token = issue_agent_jwt(
                secret="jwt-test-secret",
                agent_id="agent-foreign",
                issuer="jwt-test-issuer",
                token_version=1,
                now=1_700_000_000,
            )
            await self.registry_db.upsert_agent("agent-3")
            await self.registry_db._db.execute(
                """
                INSERT INTO agent_credentials (agent_id, token_version, updated_at)
                VALUES (?, ?, ?)
                """,
                ("agent-3", 1, int(time.time())),
            )
            await self.registry_db._db.commit()

            result = await self.registry_db.authorize_agent("agent-3", foreign_token)

        self.assertFalse(result["authorized"])
        self.assertEqual(result["reason"], "invalid bearer token")

    async def test_authorize_agent_rejects_rotated_out_jwt_version(self):
        with patch.dict(
            os.environ,
            {
                "VM_AGENT_JWT_SECRET": "jwt-test-secret",
                "VM_AGENT_JWT_ISSUER": "jwt-test-issuer",
            },
            clear=False,
        ):
            await self.registry_db.upsert_agent("agent-4")
            await self.registry_db.set_bootstrap_token("agent-4", hash_token("bootstrap-token"), int(time.time()) + 60)
            first_result = await self.registry_db.authorize_agent("agent-4", "bootstrap-token")

            await self.registry_db._db.execute(
                "UPDATE agent_credentials SET bootstrap_used_at = ?, updated_at = ? WHERE agent_id = ?",
                (int(time.time()), int(time.time()), "agent-4"),
            )
            await self.registry_db._db.commit()

            second_result = await self.registry_db.authorize_agent("agent-4", "bootstrap-token")
            stale_result = await self.registry_db.authorize_agent("agent-4", first_result["issued_secret"])
            fresh_result = await self.registry_db.authorize_agent("agent-4", second_result["issued_secret"])

        self.assertEqual(second_result["mode"], "bootstrap-recovery")
        self.assertFalse(stale_result["authorized"])
        self.assertEqual(stale_result["reason"], "invalid bearer token")
        self.assertTrue(fresh_result["authorized"])
        self.assertEqual(fresh_result["mode"], "jwt")

    async def test_rotate_agent_token_version_increments_and_clears_legacy_secret(self):
        await self.registry_db.upsert_agent("agent-5")
        await self.registry_db._db.execute(
            """
            INSERT INTO agent_credentials (agent_id, secret_hash, token_version, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("agent-5", hash_token("legacy-secret"), 2, int(time.time())),
        )
        await self.registry_db._db.commit()

        rotated = await self.registry_db.rotate_agent_token_version("agent-5")
        credentials = await self.registry_db.get_agent_credentials("agent-5")

        self.assertEqual(rotated["token_version"], 3)
        self.assertEqual(credentials["token_version"], 3)
        self.assertIsNone(credentials["secret_hash"])


if __name__ == "__main__":
    unittest.main()