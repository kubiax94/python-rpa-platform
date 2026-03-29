import tempfile
import unittest

from vm_agent_server.src.persistence.agent_registry_db import AgentRegistryDB


class AgentRegistryDBTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = AgentRegistryDB(f"{self.temp_dir.name}/agents.db")
        await self.db.start()

    async def asyncTearDown(self):
        await self.db.stop()
        self.temp_dir.cleanup()

    async def test_upsert_agent_merges_nested_metadata(self):
        await self.db.upsert_agent(
            "agent-1",
            hostname="vm-01",
            metadata={
                "guacamole": {
                    "group_name": "agent-1",
                    "connection_name": "vm-01",
                }
            },
        )

        await self.db.upsert_agent(
            "agent-1",
            metadata={
                "hostname": "vm-01",
                "os": "windows",
            },
        )

        agent = await self.db.get_agent("agent-1")
        assert agent is not None
        self.assertEqual(agent["metadata"]["guacamole"]["group_name"], "agent-1")
        self.assertEqual(agent["metadata"]["guacamole"]["connection_name"], "vm-01")
        self.assertEqual(agent["metadata"]["hostname"], "vm-01")
        self.assertEqual(agent["metadata"]["os"], "windows")


if __name__ == "__main__":
    unittest.main()