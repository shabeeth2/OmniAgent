import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from agent_backend.routers import tool_registry as registry
from agent_backend.tools.registry_connections import _build_tool


ITEM = {'name': 'read_record', 'description': 'Read a record', 'input_schema': {'type': 'object', 'properties': {}}}


class ToolEffectsTest(unittest.TestCase):
    def test_external_effects_default_safe_and_local_classification_changes_version(self):
        entry = {'id': 'connection', 'kind': 'mcp', 'tools': [ITEM]}
        unknown = _build_tool(entry, ITEM)
        self.assertEqual(unknown.metadata['effect'], 'unknown')
        # Server-supplied annotations are not a local classification.
        self.assertEqual(_build_tool(entry, {**ITEM, 'readOnlyHint': True}).metadata['effect'], 'unknown')
        read = _build_tool({**entry, 'tool_effects': {'read_record': 'read'}}, ITEM)
        self.assertEqual(read.metadata['effect'], 'read')
        self.assertNotEqual(read.metadata['configuration_hash'], unknown.metadata['configuration_hash'])
        api = _build_tool({'id': 'api', 'kind': 'api', 'method': 'GET'}, ITEM)
        self.assertEqual(api.metadata['effect'], 'read')

    def test_only_discovered_mcp_tools_can_be_classified_and_configuration_resets_policy(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(registry, 'REGISTRY_PATH', Path(directory) / 'registry.json'):
            created = registry.add_tool({'name': 'MCP', 'kind': 'mcp', 'url': 'https://example.test/mcp'})
            entries = registry.read_snapshot()
            entries[0].update(tools=[ITEM], status='passed', enabled_tools=['read_record'])
            registry._write(entries)
            changed = registry.edit_tool(created.id, {'tool_effects': {'read_record': 'read'}})
            self.assertEqual(changed.tool_effects, {'read_record': 'read'})
            self.assertEqual(changed.enabled_tools, ['read_record'])
            self.assertEqual(registry.list_tools()[0].tool_effects, {'read_record': 'read'})
            for effects in [{'missing': 'read'}, {'read_record': 'delete'}, {'read_record': []}, []]:
                with self.assertRaises(HTTPException) as error:
                    registry.edit_tool(created.id, {'tool_effects': effects})
                self.assertEqual(error.exception.status_code, 422)
            reset = registry.edit_tool(created.id, {'url': 'https://example.test/new'})
            self.assertEqual(reset.tool_effects, {})
            self.assertEqual(reset.enabled_tools, [])

    def test_existing_entries_default_to_unknown(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(registry, 'REGISTRY_PATH', Path(directory) / 'registry.json'):
            created = registry.add_tool({'name': 'MCP', 'kind': 'mcp', 'url': 'https://example.test/mcp'})
            self.assertEqual(created.tool_effects, {})
