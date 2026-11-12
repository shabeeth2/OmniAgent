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
        with patch('agent_backend.tools.rag.RagSettings',return_value=RagSettings(_env_file=None,gemini_embedding_model='gemini-embedding-2',gemini_api_key='gemini-test',gemini_base_url='https://example.test/v1beta')):
            embeddings = create_embeddings(4)
        from types import SimpleNamespace
        with patch.object(embeddings.client.models, 'embed_content') as embed:
            embed.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * 4)])
            self.assertEqual(embeddings.embed_query('hello'), [0.1] * 4)
            self.assertEqual(embed.call_args.kwargs['config'].task_type, 'RETRIEVAL_QUERY')
            self.assertEqual(embed.call_args.kwargs['config'].output_dimensionality, 4)
            embed.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * 4), SimpleNamespace(values=[0.2] * 4)])
            self.assertEqual(len(embeddings.embed_documents(['one', 'two'])), 2)
            self.assertEqual(len(embed.call_args.kwargs['contents']), 2)
            self.assertEqual(embed.call_args.kwargs['config'].task_type, 'RETRIEVAL_DOCUMENT')
        self.assertEqual(embeddings.base_url, 'https://example.test/v1beta')
        self.assertEqual(embeddings.google_api_key.get_secret_value(), 'gemini-test')
