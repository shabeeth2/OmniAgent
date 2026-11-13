import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langgraph.store.memory import InMemoryStore

from agent_backend.ingest import ingest, load_documents
from agent_backend.tools.rag import NAMESPACE, create_retrieval_tool, create_store


class TestEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [float(text.lower().count(word)) for word in ("support", "onboarding", "policy")] + [0.1]


class RagTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.embeddings = TestEmbeddings()

    def test_load_markdown_and_text(self):
        (self.docs / "onboarding.md").write_text("# Onboarding\n\nRequest access from your manager.", encoding="utf-8")
        (self.docs / "support.txt").write_text("Support responds within two business days.", encoding="utf-8")
        documents = load_documents(self.docs)
        self.assertEqual({doc.metadata["source"] for doc in documents}, {"onboarding.md", "support.txt"})
        self.assertTrue(all(doc.page_content.strip() for doc in documents))

    def test_ingest_retrieve_and_replace_store(self):
        documents = [
            Document(page_content="Support responds in two business days.", metadata={"source": "support.pdf", "citation": "support.pdf (pages 1)"}),
            Document(page_content="Onboarding requires manager approval.", metadata={"source": "onboarding.md", "citation": "onboarding.md"}),
        ]
        with patch("agent_backend.ingest.load_documents", return_value=documents):
            store = ingest(self.docs, self.embeddings, dimensions=4)
            replacement = ingest(self.docs, self.embeddings, dimensions=4)
        self.assertEqual(len(store.search(NAMESPACE)), 2)
        self.assertEqual(len(replacement.search(NAMESPACE)), 2)
        self.assertIsNot(store, replacement)
        tool = create_retrieval_tool(store)
        self.assertEqual(tool.name, "retrieve_knowledge")
        result = tool.invoke({"query": "support"})
        self.assertTrue(result.startswith("Source: support.pdf (pages 1)"))
        self.assertIn("two business days", result)
        updated = Document(page_content="Onboarding now requires IT approval.", metadata=documents[1].metadata)
        with patch("agent_backend.ingest.load_documents", return_value=[updated]):
            replacement = ingest(self.docs, self.embeddings, dimensions=4)
        self.assertEqual([item.value["text"] for item in replacement.search(NAMESPACE)], [updated.page_content])
        self.assertEqual(len(store.search(NAMESPACE)), 2)
        self.assertEqual(create_store(self.embeddings, dimensions=4).search(NAMESPACE), [])
        with self.assertRaises(ValueError):
            tool.invoke({"query": "  "})

    def test_failed_ingestion_preserves_existing_chunks(self):
        original = Document(page_content="Support policy", metadata={"source": "support.md"})
        with patch("agent_backend.ingest.load_documents", return_value=[original]):
            store = ingest(self.docs, self.embeddings, dimensions=4)
        with patch("agent_backend.ingest.load_documents", side_effect=ValueError("Unreadable PDF")):
            with self.assertRaisesRegex(ValueError, "Unreadable PDF"):
                ingest(self.docs, self.embeddings, dimensions=4)
        with patch("agent_backend.ingest.load_documents", return_value=[Document(page_content="New policy", metadata={"source": "new.md"})]):
            with patch.object(self.embeddings, "embed_documents", side_effect=RuntimeError("Embedding failed")):
                with self.assertRaisesRegex(RuntimeError, "Embedding failed"):
                    ingest(self.docs, self.embeddings, dimensions=4)
        self.assertEqual([item.value["text"] for item in store.search(NAMESPACE)], [original.page_content])

    def test_missing_or_empty_inputs(self):
        with self.assertRaises(ValueError):
            load_documents(self.root / "missing")
        with self.assertRaises(ValueError):
            load_documents(self.docs)
        with self.assertRaisesRegex(ValueError, "ingestion"):
            create_retrieval_tool(create_store(self.embeddings, dimensions=4))
        with self.assertRaisesRegex(ValueError, "semantic"):
            create_retrieval_tool(InMemoryStore())

    def test_pdf_citation_metadata(self):
        document = Document(page_content="Support policy", metadata={
            "source": str(self.docs / "policy.pdf"),
            "dl_meta": {"doc_items": [{"prov": [{"page_no": 3}, {"page_no": 2}, {"page_no": 2}]}]},
        })
        (self.docs / "policy.pdf").touch()
        with patch("langchain_docling.DoclingLoader.load", return_value=[document]):
            result = load_documents(self.docs)
        self.assertEqual(result[0].metadata, {
            "source": "policy.pdf", "pages": "2, 3", "citation": "policy.pdf (pages 2, 3)",
        })


if __name__ == "__main__":
    unittest.main()
