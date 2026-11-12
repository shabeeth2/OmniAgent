"""Process local documents into a fresh LangGraph in-memory knowledge store."""

import argparse
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langgraph.store.memory import InMemoryStore
from langgraph.store.base import PutOp

from .tools.rag import BACKEND_DIR, NAMESPACE, create_retrieval_tool, create_store


def load_documents(directory: Path) -> list[Document]:
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError(f"Document directory does not exist: {directory}")
    files = sorted(
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf"}
    )
    if not files:
        raise ValueError("No .md, .txt, or .pdf documents found.")

    # Keep Docling's conversion runtime out of the retrieval-only import path.
    from docling.chunking import HierarchicalChunker
    from langchain_docling import DoclingLoader

    documents = DoclingLoader(file_path=[str(path) for path in files], chunker=HierarchicalChunker()).load()
    for document in documents:
        metadata = document.metadata
        pages = sorted({
            provenance["page_no"]
            for item in metadata.get("dl_meta", {}).get("doc_items", [])
            for provenance in item.get("prov", [])
        })
        # Retain source citations from Docling's document metadata.
        document.metadata = {"source": Path(metadata["source"]).resolve().relative_to(directory).as_posix()}
        if pages:
            document.metadata["pages"] = ", ".join(map(str, pages))
        source = document.metadata["source"]
        document.metadata["citation"] = f"{source} (pages {document.metadata['pages']})" if pages else source
    documents = [document for document in documents if document.page_content.strip()]
    if not documents:
        raise ValueError("Documents contain no extractable text.")
    return documents


def ingest(directory: Path, embeddings: Embeddings | None = None, dimensions: int = 1024) -> InMemoryStore:
    documents = load_documents(directory)
    store = create_store(embeddings, dimensions)
    store.batch([PutOp(NAMESPACE, str(number), {"text": document.page_content, **document.metadata})
                 for number, document in enumerate(documents)])
    return store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=Path, default=BACKEND_DIR / "sample_docs")
    parser.add_argument("--query", help="Query the ingested store before the process exits.")
    parser.add_argument("--dimensions", type=int, default=1024, help="Embedding model dimensions.")
    args = parser.parse_args()
    try:
        store = ingest(args.docs, dimensions=args.dimensions)
        print("Documents ingested into memory. The index is discarded when this process exits.")
        if args.query:
            print(create_retrieval_tool(store).invoke({"query": args.query}))
    except Exception as exc:
        parser.exit(1, f"Ingestion failed: {exc}\n")


if __name__ == "__main__":
    main()
