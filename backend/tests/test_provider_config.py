import unittest
from unittest.mock import patch
from agent_backend.agent.runtime import AgentSettings, build_business_agent
from agent_backend.tools.rag import RagSettings, create_embeddings

class ProviderConfigTest(unittest.TestCase):
    def test_base_url_forwarded_to_both_clients(self):
        url='https://example.test/v1'
        with patch('agent_backend.agent.runtime.AgentSettings',return_value=AgentSettings(_env_file=None,agent_model='test',openai_api_key='test',openai_base_url=url)), patch('agent_backend.agent.runtime.ingest'), patch('agent_backend.agent.runtime.create_paypal_tools', return_value={}), patch('agent_backend.agent.runtime.create_retrieval_tool', return_value=__import__('agent_backend.tools.business', fromlist=['create_business_tools']).create_business_tools()['get_invoice']), patch('agent_backend.agent.runtime.ToolDiscovery'), patch('agent_backend.agent.runtime.ChatOpenAI') as chat:
            build_business_agent()
            self.assertEqual(chat.call_args.kwargs['base_url'],url)
        with patch('agent_backend.tools.rag.RagSettings',return_value=RagSettings(_env_file=None,jina_embedding_model='jina-embeddings-v5-omni-small',jina_api_key='jina-test',jina_base_url='https://example.test/v1/embeddings')):
            embeddings = create_embeddings(4)
        from types import SimpleNamespace
        with patch('agent_backend.tools.rag.httpx.post', return_value=SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'data': [{'index': 1, 'embedding': [0.2] * 4}, {'index': 0, 'embedding': [0.1] * 4}]},
        )) as post:
            self.assertEqual(embeddings.embed_documents(['one', 'two']), [[0.1] * 4, [0.2] * 4])
            self.assertEqual(embeddings.embed_query('hello'), [0.1] * 4)
        self.assertEqual(post.call_args.kwargs['json']['model'], 'jina-embeddings-v5-omni-small')
        self.assertEqual(post.call_args.kwargs['json']['dimensions'], 4)
        self.assertEqual(post.call_args.kwargs['json']['task'], 'retrieval.query')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer jina-test')
        self.assertEqual(embeddings.base_url, 'https://example.test/v1/embeddings')
