"""Stage 3 RAG knowledge base.

Loads Markdown docs recursively, splits them into chunks, embeds with
sentence-transformers/all-MiniLM-L6-v2 (normalized), and retrieves the
top-3 most similar chunks with NumPy cosine similarity (in-memory index).
"""

from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOP_K = 3
MAX_CHUNK_CHARS = 1000
CHUNK_OVERLAP_CHARS = 100


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS,
               overlap: int = CHUNK_OVERLAP_CHARS):
    """Split text into chunks on paragraph boundaries.

    Short documents (like the ones in knowledge_base/) yield a single chunk.
    Longer documents are packed paragraph by paragraph up to max_chars with a
    trailing overlap to preserve context across boundaries.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            # Hard-split an oversized paragraph.
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(para), max_chars - overlap):
                chunks.append(para[start:start + max_chars])
            continue
        candidate = (current + "\n\n" + para) if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (tail + "\n\n" + para) if tail else para
    if current:
        chunks.append(current)
    return chunks


class SchemaKnowledgeBase:
    def __init__(self, knowledge_dir="knowledge_base", model_name=DEFAULT_MODEL):
        self.model = SentenceTransformer(model_name)
        self.documents = []
        base = Path(knowledge_dir)
        for path in sorted(base.rglob("*.md")):
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            try:
                source = str(path.relative_to(base).as_posix())
            except ValueError:
                source = str(path)
            category = path.parent.name
            for i, chunk in enumerate(chunk_text(content)):
                self.documents.append({
                    "source": source,
                    "category": category,
                    "chunk_id": i,
                    "text": chunk,
                })
        if self.documents:
            self.embeddings = self.model.encode(
                [doc["text"] for doc in self.documents],
                normalize_embeddings=True,
            )
            self.embeddings = np.asarray(self.embeddings, dtype=np.float32)
        else:
            self.embeddings = np.zeros((0, 0), dtype=np.float32)

    def __len__(self):
        return len(self.documents)

    def search_schema_docs(self, query: str, top_k: int = DEFAULT_TOP_K):
        """Return the top-k most similar chunks (cosine similarity)."""
        if not query or not query.strip():
            return {"error": "Empty query."}
        if not self.documents:
            return {"error": "Knowledge base is empty."}
        top_k = max(1, min(top_k, len(self.documents)))
        query_vector = self.model.encode([query], normalize_embeddings=True)[0]
        scores = np.dot(self.embeddings, query_vector)
        best_indices = np.argsort(scores)[::-1][:top_k]
        return [
            {
                "source": self.documents[i]["source"],
                "category": self.documents[i]["category"],
                "text": self.documents[i]["text"],
                "similarity": float(scores[i]),
            }
            for i in best_indices
        ]
