import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from agent_backend.agent.graph import ask_user, system_search
from agent_backend.agent.discovery import catalog_operations
from agent_backend.routers.tool_registry import catalog


class CatalogApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_includes_active_external_tools_and_all_controls(self):
        external = SimpleNamespace(
            name="remote_lookup",
            description="Look up a remote record",
            metadata={"origin": "mcp", "service": "external", "version": "2"},
            args={"record_id": {"type": "string"}},
        )
        agent = SimpleNamespace(registry={"remote_lookup": external})
        manager = SimpleNamespace(snapshot=AsyncMock(return_value=agent))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            registry_agent_manager=manager,
            business_agent=SimpleNamespace(registry={"base_only": object()}),
        )))

        result = await catalog(request)
        by_name = {item["name"]: item for item in result}

        manager.snapshot.assert_awaited_once_with()
        self.assertIn("remote_lookup", by_name)
        self.assertNotIn("base_only", by_name)
        self.assertEqual(by_name["remote_lookup"]["origin"], "mcp")
        self.assertIn(system_search.name, by_name)
        self.assertIn(ask_user.name, by_name)
        self.assertEqual(len([item for item in result if item["origin"] == "catalog"]),
                         len(catalog_operations()))

    async def test_catalog_hides_registry_reload_errors(self):
        manager = SimpleNamespace(snapshot=AsyncMock(side_effect=ValueError("secret token")))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            registry_agent_manager=manager,
            business_agent=SimpleNamespace(registry={}),
        )))

        with self.assertRaises(HTTPException) as error:
            await catalog(request)

        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("secret token", error.exception.detail)


if __name__ == "__main__":
    unittest.main()
