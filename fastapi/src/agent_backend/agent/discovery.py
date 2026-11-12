"""Semantic tool metadata index, separate from knowledge retrieval."""
import json
import hashlib
import re
from pathlib import Path
from ..tools.rag import create_store, create_embeddings
from ..utils.embedding_cache import CachedEmbeddings
from langgraph.store.base import PutOp

NAMESPACE = ('tools',)


def catalog_operations():
    return json.loads((Path(__file__).resolve().parents[1] / 'catalog/paypal-v1.json').read_text(encoding='utf-8'))['operations']


def catalog_descriptions(registry):
    return {**{row['id']: row['description'] for row in catalog_operations()}, **ToolDiscovery.describe(registry)}

class ToolDiscovery:
    def __init__(self, registry, embeddings=None, dimensions=1536, descriptions=None, cache_path=None, embedding_id=None):
        self.registry = registry
        if cache_path is not None:
            embeddings = embeddings or create_embeddings(dimensions)
            if not embedding_id:
                from ..tools.rag import embedding_identity
                embedding_id = embedding_identity(embeddings)
            embeddings = CachedEmbeddings(embeddings, cache_path, embedding_id, dimensions)
        self.store = create_store(embeddings, dimensions)
        self.descriptions = descriptions if descriptions is not None else self.describe(registry)
        self.version = hashlib.sha256(json.dumps(self.descriptions, sort_keys=True).encode()).hexdigest()[:16]
        self.store.batch([PutOp(NAMESPACE, name, {'text': description}) for name, description in self.descriptions.items()])

    @staticmethod
    def describe(registry):
        return {name:f'{name}: {tool.description}\nservice={(tool.metadata or {}).get("service", "external")} version={(tool.metadata or {}).get("version", "1")}\n{json.dumps(tool.args, sort_keys=True)}' for name,tool in registry.items()}

    @staticmethod
    def tokens(text):
        return {word.rstrip('s') for word in re.findall(r'[a-z0-9]+', text.lower().replace('_', ' ')) if len(word)>1}

    async def candidates(self, query):
        semantic = await self.store.asearch(NAMESPACE, query=query, limit=20)
        scores = {row.key: max(0, float(row.score or 0)) for row in semantic}
        tokens = self.tokens(query)
        ranked = []
        for name, description in self.descriptions.items():
            lexical = len(tokens & self.tokens(description)) / max(1, len(tokens))
            score = .5 * scores.get(name, 0) + .5 * lexical
            ranked.append({'id': name, 'description': description, 'score': round(score, 6),
                           'executable': name in self.registry})
        return sorted(ranked, key=lambda row: (-row['score'], row['id']))[:5]

    async def search(self, query):
        return [row['id'] for row in await self.candidates(query) if row['executable']]
