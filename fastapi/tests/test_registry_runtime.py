import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from agent_backend.agent.runtime import RegistryAgentManager


class RegistryRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.base = SimpleNamespace(model=object(), registry={"built_in": object()}, clock=object(), timeout=45, checkpointer=object())
        self.manager = RegistryAgentManager(self.base)
        patcher = patch('agent_backend.agent.runtime.catalog_descriptions', return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_edits_apply_to_next_request_not_existing_agent(self):
        entries = [{"id": "external", "enabled_tools": ["external"]}]
        async def load(snapshot):
            return {"external": object()} if snapshot and snapshot[0]["enabled_tools"] else {}
        def build(model, discovery, registry, **kwargs):
            return SimpleNamespace(registry=registry, model=model, **kwargs)
        with patch("agent_backend.routers.tool_registry.read_snapshot", side_effect=lambda: entries), \
             patch("agent_backend.tools.registry_connections.load_enabled_tools", side_effect=load) as loader, \
             patch("agent_backend.agent.runtime.ToolDiscovery"), \
             patch("agent_backend.agent.runtime.BusinessAgent", side_effect=build):
            active = await self.manager.snapshot(fresh=True)
            self.assertIn("external", active.registry)
            self.assertIs(await self.manager.snapshot(fresh=True), active)
            self.assertEqual(loader.call_count, 1)
            entries[0]["enabled_tools"] = []
            disabled = await self.manager.snapshot(fresh=True)
            self.assertNotIn("external", disabled.registry)
            self.assertIn("external", active.registry)
            entries.clear()
            deleted = await self.manager.snapshot(fresh=True)
            self.assertNotIn("external", deleted.registry)
            self.assertIs(deleted.model, self.base.model)
            self.assertIs(deleted.clock, self.base.clock)
            self.assertEqual(deleted.timeout, 45)

    async def test_concurrent_requests_share_atomic_snapshot(self):
        with patch("agent_backend.routers.tool_registry.read_snapshot", return_value=[]), \
             patch("agent_backend.tools.registry_connections.load_enabled_tools", new_callable=AsyncMock, return_value={}) as loader, \
             patch("agent_backend.agent.runtime.ToolDiscovery") as discovery, \
             patch("agent_backend.agent.runtime.BusinessAgent") as build:
            first, second = await asyncio.gather(self.manager.snapshot(), self.manager.snapshot())
            self.assertIs(first, second)
            self.assertIs(first, self.base)
            loader.assert_awaited_once()
            discovery.assert_not_called()
            build.assert_not_called()

    async def test_failed_reload_preserves_published_snapshot(self):
        with patch("agent_backend.routers.tool_registry.read_snapshot", return_value=[]), \
             patch("agent_backend.tools.registry_connections.load_enabled_tools", new_callable=AsyncMock, return_value={}) as loader, \
             patch("agent_backend.agent.runtime.ToolDiscovery"), \
             patch("agent_backend.agent.runtime.BusinessAgent"):
            active = await self.manager.snapshot(fresh=True)
            loader.side_effect = ValueError("failed")
            with patch("agent_backend.routers.tool_registry.read_snapshot", return_value=[{"enabled_tools": ["external"]}]):
                with self.assertRaises(ValueError):
                    await self.manager.snapshot(fresh=True)
            self.assertIs(await self.manager.snapshot(fresh=True), active)

    async def test_snapshot_failure_does_not_write_chat_or_expose_credentials(self):
        from fastapi import HTTPException
        from agent_backend.routers.chat import chat_endpoint
        from agent_backend.schemas import ChatRequest

        manager = SimpleNamespace(snapshot=AsyncMock(side_effect=ValueError("secret-token")))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(registry_agent_manager=manager)))
        db = Mock()
        with self.assertRaises(HTTPException) as error:
            await chat_endpoint(ChatRequest(message="hello"), request, db)
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("secret-token", error.exception.detail)
        self.assertEqual(db.mock_calls, [])

    async def test_requests_keep_published_snapshot_while_reload_waits(self):
        entries = []
        started, release = asyncio.Event(), asyncio.Event()
        async def load(snapshot):
            if snapshot:
                started.set()
                await release.wait()
            return {}
        with patch('agent_backend.routers.tool_registry.read_snapshot', side_effect=lambda: entries), patch('agent_backend.tools.registry_connections.load_enabled_tools', side_effect=load):
            active = await self.manager.snapshot()
            entries.append({'id': 'new'})
            self.assertIs(await self.manager.snapshot(), active)
            await started.wait()
            self.assertIs(await asyncio.wait_for(self.manager.snapshot(), .2), active)
            release.set()
            self.assertIs(await self.manager.snapshot(fresh=True), active)

    async def test_fresh_snapshot_observes_second_edit_during_reload(self):
        entries = []
        started, release = asyncio.Event(), asyncio.Event()
        versions = []
        async def load(snapshot):
            versions.append(snapshot)
            if snapshot == [{'id': 'first'}]:
                started.set()
                await release.wait()
            return {}
        with patch('agent_backend.routers.tool_registry.read_snapshot', side_effect=lambda: entries), patch('agent_backend.tools.registry_connections.load_enabled_tools', side_effect=load):
            await self.manager.snapshot()
            entries.append({'id': 'first'})
            await self.manager.snapshot()
            await started.wait()
            entries[0] = {'id': 'second'}
            fresh = asyncio.create_task(self.manager.snapshot(fresh=True))
            release.set()
            await fresh
            self.assertEqual(self.manager._entries, [{'id': 'second'}])
            self.assertEqual(versions[-1], [{'id': 'second'}])
