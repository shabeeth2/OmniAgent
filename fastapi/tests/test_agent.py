import asyncio
import unittest
from datetime import date
from langchain_core.messages import AIMessage, HumanMessage
from agent_backend.agent.graph import BusinessAgent, INCOMPLETE
from agent_backend.tools.business import create_business_tools
from agent_backend.agent.discovery import ToolDiscovery
from test_rag import TestEmbeddings

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from pydantic import Field


class Model(FakeMessagesListChatModel):
    bound: list = Field(default_factory=list)

    def __init__(self, responses):
        super().__init__(responses=responses)

    def bind_tools(self, tools, **kwargs):
        self.bound.append([tool.name for tool in tools])
        return self


def call(name, args, id='1'):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': id}])


class Discovery:
    async def search(self, query):
        return ['aggregate_outstanding', 'aggregate_outstanding', 'missing']


class GraphTest(unittest.IsolatedAsyncioTestCase):
    async def test_agent_discovers_executes_and_rediscovers(self):
        model = Model([
            call('system_search', {'query': 'totals'}),
            call('aggregate_outstanding', {'start_date': '2026-10-01', 'end_date': '2026-11-01'}),
            call('system_search', {'query': 'again'}),
            AIMessage(content='USD 125.50; EUR 20.00'),
        ])
        agent = BusinessAgent(model, Discovery(), create_business_tools(), clock=lambda: date(2026, 11, 11))
        outcome = await agent.run([HumanMessage(content='last month')])
        self.assertEqual(outcome.status, 'completed')
        self.assertEqual(outcome.content, 'USD 125.50; EUR 20.00')
        self.assertEqual(model.bound[0], ['system_search', 'ask_user'])
        self.assertIn('aggregate_outstanding', model.bound[1])

    async def test_unselected_tool_is_rejected_before_execution(self):
        model = Model([call('get_invoice', {'invoice_id': 'i1'}), AIMessage(content='I could not use it.')])
        agent = BusinessAgent(model, Discovery(), create_business_tools())
        outcome = await agent.run([HumanMessage(content='read it')])
        self.assertEqual(outcome.status, 'failed')
        self.assertIn('Tool not selected', outcome.content)

    async def test_reused_tool_call_id_does_not_bypass_selection_gate(self):
        executed = []
        from langchain.tools import tool
        @tool
        def unselected(value: int) -> str:
            """Read a local value."""
            executed.append(value)
            return str(value)
        unselected.metadata = {'origin': 'local', 'effect': 'read'}
        model = Model([call('system_search', {'query': 'totals'}, 'reused'),
                       call('unselected', {'value': 1}, 'reused'), AIMessage(content='blocked')])
        outcome = await BusinessAgent(model, Discovery(), {'unselected': unselected}).run([])
        self.assertEqual(outcome.status, 'failed')
        self.assertEqual(executed, [])

    async def test_independent_classified_reads_run_concurrently(self):
        from langchain.tools import tool
        started = []
        release = asyncio.Event()
        @tool
        async def read_one(value: int) -> str:
            """Read the first independent record."""
            started.append('one')
            if len(started) == 2:
                release.set()
            await asyncio.wait_for(release.wait(), 2)
            return str(value)
        @tool
        async def read_two(value: int) -> str:
            """Read the second independent record."""
            started.append('two')
            if len(started) == 2:
                release.set()
            await asyncio.wait_for(release.wait(), 2)
            return str(value)
        for read in (read_one, read_two):
            read.metadata = {'origin': 'api', 'effect': 'read'}
        class ReadDiscovery:
            async def search(self, query):
                return ['read_one', 'read_two']
        model = Model([call('system_search', {'query': 'both'}), AIMessage(content='', tool_calls=[
            {'name': 'read_one', 'args': {'value': 1}, 'id': 'one'},
            {'name': 'read_two', 'args': {'value': 2}, 'id': 'two'},
        ]), AIMessage(content='done')])
        outcome = await BusinessAgent(model, ReadDiscovery(), {'read_one': read_one, 'read_two': read_two}).run([])
        self.assertEqual(outcome.status, 'completed')
        self.assertCountEqual(started, ['one', 'two'])

    async def test_control_tools_must_be_called_alone(self):
        model = Model([
            AIMessage(content='', tool_calls=[
                {'name': 'system_search', 'args': {'query': 'invoice'}, 'id': 'search'},
                {'name': 'get_invoice', 'args': {'invoice_id': 'i1'}, 'id': 'read'},
            ]),
            AIMessage(content='No action was taken.'),
        ])
        agent = BusinessAgent(model, Discovery(), create_business_tools())
        outcome = await agent.run([HumanMessage(content='read it')])
        self.assertEqual(outcome.status, 'failed')
        self.assertEqual(model.bound, [['system_search', 'ask_user']])

    async def test_discovery_budget_is_reported(self):
        model = Model([call('system_search', {'query': 'unknown'}, str(i)) for i in range(4)] + [AIMessage(content='No capability.')])
        class EmptyDiscovery:
            async def search(self, query):
                return []
        outcome = await BusinessAgent(model, EmptyDiscovery(), {}).run([])
        self.assertEqual(outcome.status, 'budget_exhausted')

    async def test_execution_budget_stops_after_twenty_calls(self):
        from langchain.tools import tool
        executed = []
        @tool
        def read_record(value: int) -> str:
            """Read a local record."""
            executed.append(value)
            return str(value)
        read_record.metadata = {'origin': 'local', 'effect': 'read'}
        calls = AIMessage(content='', tool_calls=[
            {'name': 'read_record', 'args': {'value': number}, 'id': f'read-{number}'}
            for number in range(21)
        ])
        class ReadDiscovery:
            async def search(self, query):
                return ['read_record']
        model = Model([call('system_search', {'query': 'records'}), calls, AIMessage(content='partial')])
        outcome = await BusinessAgent(model, ReadDiscovery(), {'read_record': read_record}).run([])
        self.assertEqual(outcome.status, 'budget_exhausted')
        self.assertEqual(len(executed), 20)

    async def test_context_budget_is_reported(self):
        outcome = await BusinessAgent(Model([AIMessage(content='unreachable')]), None, {}, context_budget=1).run(
            [HumanMessage(content='hello')])
        self.assertEqual(outcome.status, 'budget_exhausted')

    async def test_timeout_and_cancellation(self):
        class Slow(Model):
            async def ainvoke(self, messages, **kwargs):
                await asyncio.sleep(10)
                return await super().ainvoke(messages, **kwargs)

        agent = BusinessAgent(Slow([]), Discovery(), {}, timeout=.01)
        self.assertEqual((await agent.run([])).content, INCOMPLETE)
        task = asyncio.create_task(BusinessAgent(Slow([]), Discovery(), {}).run([]))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_tool_discovery_index(self):
        registry = create_business_tools()
        index = ToolDiscovery(registry, TestEmbeddings(), 4)
        self.assertTrue(set(await index.search('invoice')).issubset(registry))


if __name__ == '__main__':
    unittest.main()
