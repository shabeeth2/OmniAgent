import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agent_backend.utils.budgets import bounded_messages, bounded_result, ContextBudgetExceeded
from agent_backend.tools.registry_connections import _build_tool, ConnectionFailure


class ContextTest(unittest.TestCase):
    def test_discards_whole_old_turns_and_preserves_current_call_pairs(self):
        messages = [HumanMessage(content='old'*1000), AIMessage(content='old answer'), HumanMessage(content='current'),
                    AIMessage(content='', tool_calls=[{'name':'read','args':{},'id':'a'}]), ToolMessage(content='result', tool_call_id='a')]
        trimmed = bounded_messages('system', messages, [], 1500)
        self.assertEqual([m.type for m in trimmed], ['system', 'human', 'ai', 'tool'])
        self.assertEqual(trimmed[1].content, 'current')
        with self.assertRaises(ContextBudgetExceeded):
            bounded_messages('system', [HumanMessage(content='x'*10000)], [], 1500)

    def test_large_result_explicitly_incomplete(self):
        result = bounded_result('x'*13000)
        self.assertLessEqual(len(result), 12000)
        self.assertIn('"complete": false', result)

    def test_tiny_result_budget_fails_instead_of_looping(self):
        with self.assertRaises(ValueError):
            bounded_result('x'*1000, limit=10)


class McpDriftTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_schema_or_description_change_blocks_execution(self):
        saved = {'name':'read', 'description':'Read record', 'input_schema':{'type':'object','properties':{}}}
        for change in [{'description':'Delete record'}, {'input_schema':{'type':'object','required':['id'],'properties':{'id':{'type':'string'}}}}]:
            current = {**saved, **change}
            remote = SimpleNamespace(name=current['name'], description=current['description'], args_schema=current['input_schema'], ainvoke=AsyncMock())
            @asynccontextmanager
            async def adapter(entry):
                yield SimpleNamespace(list_tools=AsyncMock(return_value=[remote]))
            entry = {'id':'123', 'kind':'mcp'}
            with patch('agent_backend.tools.registry_connections.mcp_adapter', adapter):
                with self.assertRaises(ConnectionFailure):
                    await _build_tool(entry, saved).ainvoke({})
            remote.ainvoke.assert_not_awaited()
