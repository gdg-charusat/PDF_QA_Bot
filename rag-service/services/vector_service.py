"""
services/vector_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Manages FAISS vector-store creation, session-scoped storage, and
similarity-search helpers.

Sessions are stored in an in-memory dict protected by a ``threading.Lock``
so the service is safe for concurrent FastAPI workers.
"""

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.config import SESSION_TIMEOUT
from services.document_service import chunk_documents, load_pdf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import placeholders
# ---------------------------------------------------------------------------
_FAISS = None
_HuggingFaceEmbeddings = None


def _ensure_faiss() -> bool:
    """Lazily import LangChain's FAISS wrapper. Returns False if unavailable."""
    global _FAISS
    if _FAISS is not None:
        return True
    try:
        from langchain_community.vectorstores import FAISS  # type: ignore

        _FAISS = FAISS
        return True
    except Exception as exc:  # noqa: BLE001 – broken transitive deps can raise NameError etc.
        logger.warning("FAISS unavailable: %s", exc)
        return False


def _ensure_embeddings() -> bool:
    """Lazily import HuggingFaceEmbeddings. Returns False if unavailable."""
    global _HuggingFaceEmbeddings
    if _HuggingFaceEmbeddings is not None:
        return True
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore

        _HuggingFaceEmbeddings = HuggingFaceEmbeddings
        return True
    except Exception as exc:  # noqa: BLE001 – broken transitive deps can raise NameError etc.
        logger.warning("HuggingFaceEmbeddings unavailable: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Singleton embedding model
# ---------------------------------------------------------------------------
_embedding_model = None


def get_embedding_model() -> Optional[Any]:
    """
    Return the shared ``HuggingFaceEmbeddings`` instance, loading it on first
    call.  Returns ``None`` when the dependency is unavailable.
    """
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    if not _ensure_embeddings():
        return None
    try:
        _embedding_model = _HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        return _embedding_model
    except Exception as exc:
        logger.error("Failed to load embedding model: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Dummy vector store – used when FAISS / embeddings are unavailable
# ---------------------------------------------------------------------------
class _DummyVectorStore:
    """Minimal keyword-free vector store for fallback / testing."""

    def __init__(self, docs: List[Any]) -> None:
        self._docs = docs

    @classmethod
    def from_documents(cls, docs: List[Any], embeddings: Any = None) -> "_DummyVectorStore":
        return cls(docs)

    def similarity_search(self, query: str, k: int = 4) -> List[Any]:  # noqa: ARG002
        return self._docs[:k]


# ---------------------------------------------------------------------------
# Session storage
# ---------------------------------------------------------------------------
# Format: { session_id: { "vectorstores": [store, ...], "last_accessed": float } }
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()


def cleanup_expired_sessions() -> None:
    """Remove sessions that have not been accessed within *SESSION_TIMEOUT* seconds."""
    current_time = time.time()
    with _sessions_lock:
        expired = [
            sid
            for sid, data in list(_sessions.items())
            if current_time - data["last_accessed"] > SESSION_TIMEOUT
        ]
        for sid in expired:
            del _sessions[sid]
    if expired:
        logger.info("Cleaned up %d expired session(s).", len(expired))


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------
def build_vectorstore(chunks: List[Any]) -> Any:
    """
    Build and return a vector store from *chunks*.

    Falls back to :class:`_DummyVectorStore` when FAISS or the embedding model
    are unavailable.
    """
    emb = get_embedding_model()
    if _ensure_faiss() and emb is not None:
        return _FAISS.from_documents(chunks, emb)
    return _DummyVectorStore.from_documents(chunks)


def create_session_from_file(file_path: str) -> str:
    """
    Load a PDF file, chunk it, build a vector store, persist the session, and
    return the new ``session_id``.

    The file at *file_path* is deleted after processing (best-effort).

    Parameters
    ----------
    file_path:
        Absolute path to the uploaded PDF on disk.

    Returns
    -------
    str
        A freshly generated UUID4 session identifier.
    """
    try:
        docs = load_pdf(file_path)
        chunks = chunk_documents(docs)
        vectorstore = build_vectorstore(chunks)

        session_id = str(uuid4())
        with _sessions_lock:
            _sessions[session_id] = {
                "vectorstores": [vectorstore],
                "last_accessed": time.time(),
            }
        logger.info("Session created: %s", session_id)
        return session_id
    finally:
        # Always attempt to remove the temporary file
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass


def get_vectorstores_for_sessions(session_ids: List[str]) -> List[Any]:
    """
    Return all vector stores associated with *session_ids*, updating their
    ``last_accessed`` timestamps.

    Parameters
    ----------
    session_ids:
        List of session UUIDs to look up.

    Returns
    -------
    list
        Flat list of vector-store objects across all requested sessions.
    """
    vectorstores: List[Any] = []
    with _sessions_lock:
        for sid in session_ids:
            session = _sessions.get(sid)
            if session:
                session["last_accessed"] = time.time()
                vectorstores.extend(session["vectorstores"])
    return vectorstores


def similarity_search(
    vectorstores: List[Any], query: str, k: int = 4
) -> List[Any]:
    """
    Run *query* against every store in *vectorstores* and return the combined
    top-*k* results per store.

    Parameters
    ----------
    vectorstores:
        Vector stores to query.
    query:
        Natural-language search string.
    k:
        Number of results to retrieve per store.

    Returns
    -------
    list
        Combined list of matching document chunks.
    """
    docs: List[Any] = []
    for vs in vectorstores:
        docs.extend(vs.similarity_search(query, k=k))
    return docs


def get_context_per_session(
    session_ids: List[str], query: str = "main topics", k: int = 4
) -> List[str]:
    """
    Return one context string per session in *session_ids*.

    Only sessions that exist are included; missing IDs are silently skipped.
    Each context is built by running *query* against the session's first
    vector store and joining the resulting page contents.

    Parameters
    ----------
    session_ids:
        Ordered list of session UUIDs to query.
    query:
        Search string passed to each vector store.
    k:
        Number of chunks to retrieve per session.

    Returns
    -------
    list[str]
        One concatenated context string per found session (same order as
        *session_ids*).
    """
    # Snapshot vectorstore references inside the lock (fast), then search
    # outside the lock to avoid blocking other threads during inference.
    stores: List[Any] = []
    with _sessions_lock:
        for sid in session_ids:
            session = _sessions.get(sid)
            if session:
                session["last_accessed"] = time.time()
                stores.append(session["vectorstores"][0])

    contexts: List[str] = []
    for vs in stores:
        chunks = vs.similarity_search(query, k=k)
        contexts.append("\n".join(c.page_content for c in chunks))
    return contexts
