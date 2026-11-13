import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_backend.agent.discovery import ToolDiscovery
from agent_backend.tools.business import create_business_tools
from test_rag import TestEmbeddings


class DiscoveryCacheTest(unittest.IsolatedAsyncioTestCase):
    def test_batch_misses_order_duplicates_and_identity_isolation(self):
        from agent_backend.utils.embedding_cache import CachedEmbeddings
        class Counting(TestEmbeddings):
            def __init__(self): self.batches = []; self.queries = 0
            def embed_documents(self, texts):
                self.batches.append(list(texts))
                return super().embed_documents(texts)
            def embed_query(self, text):
                self.queries += 1
                return super().embed_query(text)
        with TemporaryDirectory() as directory:
            delegate = Counting()
            path = Path(directory)/'cache.db'
            old = CachedEmbeddings(delegate, path, 'legacy', 4)
            expected = old.embed_documents(['one', 'two', 'one'])
            self.assertEqual(delegate.batches, [['one', 'two']])
            self.assertEqual(expected[0], expected[2])
            self.assertEqual(CachedEmbeddings(delegate, path, 'legacy', 4).embed_documents(['one', 'two', 'one']), expected)
            self.assertEqual(len(delegate.batches), 1)
            new = CachedEmbeddings(delegate, path, 'new-sdk-tasks', 4)
            new.embed_documents(['one'])
            self.assertEqual(new.misses, 1)
            queries_before = delegate.queries
            new.embed_query('query'); new.embed_query('query')
            self.assertEqual(delegate.queries - queries_before, 2)

    async def test_restarts_reuse_vectors_and_changed_description_only(self):
        class Counting(TestEmbeddings):
            def __init__(self): self.count = 0
            def embed_documents(self, texts):
                self.count += len(texts)
                return super().embed_documents(texts)
        with TemporaryDirectory() as directory:
            embed = Counting()
            registry = create_business_tools()
            options = {'embeddings': embed, 'dimensions': 4, 'cache_path': Path(directory)/'cache.db', 'embedding_id': 'test-v1'}
            ToolDiscovery(registry, **options)
            self.assertEqual(embed.count, 4)
            index = ToolDiscovery(registry, **options)
            self.assertEqual(embed.count, 4)
            registry['get_invoice'].description += ' New wording.'
            ToolDiscovery(registry, **options)
            self.assertEqual(embed.count, 5)
            candidates = await index.candidates('get invoice')
            self.assertLessEqual(len(candidates), 5)
            self.assertTrue(all('score' in row and 'executable' in row for row in candidates))

    async def test_unavailable_descriptors_never_become_executable(self):
        index = ToolDiscovery({}, TestEmbeddings(), 4, descriptions={'paypal_delete_invoice':'Delete a PayPal invoice.'})
        self.assertEqual(await index.search('delete invoice'), [])
        self.assertFalse((await index.candidates('delete invoice'))[0]['executable'])
