"""Content-addressed embedding cache. Query text is never persisted."""
import hashlib
import json
import sqlite3
from contextlib import closing
from langchain_core.embeddings import Embeddings


class CachedEmbeddings(Embeddings):
    def __init__(self, delegate, path, identity, dimensions):
        self.delegate, self.path = delegate, path
        self.identity = f'{identity}:{dimensions}'
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS embedding_cache (key TEXT PRIMARY KEY, vector TEXT NOT NULL)')
            db.commit()
        self.misses = 0

    def embed_documents(self, texts):
        keys = [hashlib.sha256((self.identity+'\0'+text).encode()).hexdigest() for text in texts]
        with closing(sqlite3.connect(self.path)) as db:
            cached = {key: json.loads(row[0]) for key in dict.fromkeys(keys)
                      if (row := db.execute('SELECT vector FROM embedding_cache WHERE key=?', (key,)).fetchone())}
            missing = dict((key, text) for key, text in zip(keys, texts) if key not in cached)
            if missing:
                vectors = self.delegate.embed_documents(list(missing.values()))
                if len(vectors) != len(missing):
                    raise ValueError('Embedding provider returned an unexpected vector count')
                cached.update(zip(missing, vectors))
                db.executemany('INSERT OR IGNORE INTO embedding_cache VALUES (?,?)',
                               [(key, json.dumps(cached[key])) for key in missing])
                db.commit()
                self.misses += len(missing)
        return [cached[key] for key in keys]

    def embed_query(self, text):
        return self.delegate.embed_query(text)
