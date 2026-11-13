import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage
from agent_backend.agent.graph import BusinessAgent
from agent_backend.tools.rag import create_retrieval_tool, create_store, NAMESPACE
from test_agent import Model, call, Discovery
from test_rag import TestEmbeddings


class SpecialistTest(unittest.IsolatedAsyncioTestCase):
    async def test_cited_knowledge_available_without_discovery(self):
        store = create_store(TestEmbeddings(), 4)
        store.put(NAMESPACE, 'support', {'text': 'Support responds in two business days.', 'citation': 'support.txt'})
        retrieval = create_retrieval_tool(store)
        model = Model([call('retrieve_knowledge', {'query': 'support'}), AIMessage(content='Two business days [support.txt].')])
        agent = BusinessAgent(model, Discovery(), {'retrieve_knowledge': retrieval})
        result = await agent.run([HumanMessage(content='Support response time?')])
        self.assertEqual(result.status, 'completed')
        self.assertIn('support.txt', result.content)
        self.assertIn('retrieve_knowledge', model.bound[0])
        state = await agent.graph.aget_state({'configurable': {'thread_id': 'unused'}})
        self.assertFalse(state.values)

    async def test_status_search_uses_request_scope_without_discovery(self):
        model = Model([call('system_search', {'mode': 'status'}), AIMessage(content='Previous request failed.')])
        agent = BusinessAgent(model, Discovery(), {})
        seen = []
        await agent.run([], on_status=lambda: seen.append('scoped') or [{'status': 'failed'}])
        self.assertEqual(seen, ['scoped'])

    async def test_empty_knowledge_is_explicitly_unavailable(self):
        tool = create_retrieval_tool(create_store(TestEmbeddings(), 4), allow_empty=True)
        self.assertIn('unavailable', tool.invoke({'query': 'support'}).lower())
