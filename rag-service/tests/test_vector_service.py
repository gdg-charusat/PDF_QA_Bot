"""
Unit tests for services/vector_service.py

All heavy ML dependencies (FAISS, HuggingFaceEmbeddings) are mocked so
these tests run in a plain Python environment.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

import services.vector_service as vs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Doc:
    def __init__(self, text: str):
        self.page_content = text


def _make_dummy_store(docs=None):
    """Return a _DummyVectorStore instance pre-loaded with docs."""
    docs = docs or [_Doc("hello world")]
    return vs._DummyVectorStore(docs)


# ---------------------------------------------------------------------------
# _DummyVectorStore
# ---------------------------------------------------------------------------

class TestDummyVectorStore:
    def test_from_documents_returns_instance(self):
        docs = [_Doc("a"), _Doc("b")]
        store = vs._DummyVectorStore.from_documents(docs)
        assert isinstance(store, vs._DummyVectorStore)

    def test_similarity_search_respects_k(self):
        docs = [_Doc(str(i)) for i in range(10)]
        store = vs._DummyVectorStore(docs)
        results = store.similarity_search("query", k=3)
        assert len(results) == 3

    def test_similarity_search_returns_all_if_k_exceeds_docs(self):
        docs = [_Doc("x")]
        store = vs._DummyVectorStore(docs)
        results = store.similarity_search("q", k=100)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# get_embedding_model
# ---------------------------------------------------------------------------

class TestGetEmbeddingModel:
    def test_returns_none_when_hf_unavailable(self):
        saved = vs._HuggingFaceEmbeddings
        vs._HuggingFaceEmbeddings = None
        vs._embedding_model = None

        saved_ensure = vs._ensure_embeddings
        vs._ensure_embeddings = lambda: False
        try:
            result = vs.get_embedding_model()
        finally:
            vs._HuggingFaceEmbeddings = saved
            vs._ensure_embeddings = saved_ensure
            vs._embedding_model = None

        assert result is None

    def test_caches_model_on_second_call(self):
        sentinel = object()
        vs._embedding_model = sentinel
        try:
            result = vs.get_embedding_model()
        finally:
            vs._embedding_model = None
        assert result is sentinel


# ---------------------------------------------------------------------------
# build_vectorstore
# ---------------------------------------------------------------------------

class TestBuildVectorstore:
    def test_returns_dummy_store_when_faiss_absent(self):
        saved_faiss = vs._FAISS
        saved_emb = vs._embedding_model
        vs._FAISS = None
        vs._embedding_model = None

        saved_ensure_faiss = vs._ensure_faiss
        vs._ensure_faiss = lambda: False
        try:
            store = vs.build_vectorstore([_Doc("test")])
        finally:
            vs._FAISS = saved_faiss
            vs._embedding_model = saved_emb
            vs._ensure_faiss = saved_ensure_faiss

        assert isinstance(store, vs._DummyVectorStore)

    def test_uses_faiss_when_available(self):
        mock_faiss = MagicMock()
        mock_store = MagicMock()
        mock_faiss.from_documents.return_value = mock_store
        mock_emb = MagicMock()

        saved_faiss = vs._FAISS
        saved_emb = vs._embedding_model
        vs._FAISS = mock_faiss
        vs._embedding_model = mock_emb

        saved_ensure = vs._ensure_faiss
        vs._ensure_faiss = lambda: True
        try:
            result = vs.build_vectorstore([_Doc("doc")])
        finally:
            vs._FAISS = saved_faiss
            vs._embedding_model = saved_emb
            vs._ensure_faiss = saved_ensure

        mock_faiss.from_documents.assert_called_once()
        assert result is mock_store


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    def setup_method(self):
        """Clear session state before every test."""
        with vs._sessions_lock:
            vs._sessions.clear()

    def teardown_method(self):
        with vs._sessions_lock:
            vs._sessions.clear()

    # -- create_session_from_file --

    def test_create_session_from_file_returns_uuid(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"dummy")

        fake_docs = [_Doc("content")]
        fake_chunks = [_Doc("chunk")]
        fake_store = _make_dummy_store(fake_chunks)

        with (
            patch("services.vector_service.load_pdf", return_value=fake_docs),
            patch("services.vector_service.chunk_documents", return_value=fake_chunks),
            patch("services.vector_service.build_vectorstore", return_value=fake_store),
        ):
            sid = vs.create_session_from_file(str(pdf))

        assert isinstance(sid, str) and len(sid) == 36  # UUID4

    def test_create_session_stores_vectorstore(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"dummy")

        fake_store = _make_dummy_store()

        with (
            patch("services.vector_service.load_pdf", return_value=[_Doc("x")]),
            patch("services.vector_service.chunk_documents", return_value=[_Doc("x")]),
            patch("services.vector_service.build_vectorstore", return_value=fake_store),
        ):
            sid = vs.create_session_from_file(str(pdf))

        with vs._sessions_lock:
            assert sid in vs._sessions
            assert vs._sessions[sid]["vectorstores"][0] is fake_store

    def test_create_session_deletes_file_after_processing(self, tmp_path):
        pdf = tmp_path / "todelete.pdf"
        pdf.write_bytes(b"dummy")

        with (
            patch("services.vector_service.load_pdf", return_value=[_Doc("x")]),
            patch("services.vector_service.chunk_documents", return_value=[_Doc("x")]),
            patch("services.vector_service.build_vectorstore", return_value=_make_dummy_store()),
        ):
            vs.create_session_from_file(str(pdf))

        assert not pdf.exists()

    def test_create_session_deletes_file_even_on_error(self, tmp_path):
        pdf = tmp_path / "err.pdf"
        pdf.write_bytes(b"dummy")

        with (
            patch("services.vector_service.load_pdf", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            vs.create_session_from_file(str(pdf))

        assert not pdf.exists()

    # -- get_vectorstores_for_sessions --

    def test_returns_vectorstores_for_valid_session_ids(self):
        store = _make_dummy_store()
        sid = "test-session-id"
        with vs._sessions_lock:
            vs._sessions[sid] = {"vectorstores": [store], "last_accessed": time.time()}

        result = vs.get_vectorstores_for_sessions([sid])
        assert result == [store]

    def test_returns_empty_for_unknown_session_id(self):
        result = vs.get_vectorstores_for_sessions(["nonexistent"])
        assert result == []

    def test_updates_last_accessed(self):
        store = _make_dummy_store()
        sid = "ts-2"
        old_time = time.time() - 100
        with vs._sessions_lock:
            vs._sessions[sid] = {"vectorstores": [store], "last_accessed": old_time}

        vs.get_vectorstores_for_sessions([sid])

        with vs._sessions_lock:
            assert vs._sessions[sid]["last_accessed"] > old_time

    # -- cleanup_expired_sessions --

    def test_removes_expired_sessions(self):
        sid = "expired"
        with vs._sessions_lock:
            vs._sessions[sid] = {
                "vectorstores": [],
                "last_accessed": time.time() - vs.SESSION_TIMEOUT - 1,
            }

        vs.cleanup_expired_sessions()

        with vs._sessions_lock:
            assert sid not in vs._sessions

    def test_keeps_active_sessions(self):
        sid = "active"
        with vs._sessions_lock:
            vs._sessions[sid] = {
                "vectorstores": [],
                "last_accessed": time.time(),
            }

        vs.cleanup_expired_sessions()

        with vs._sessions_lock:
            assert sid in vs._sessions

    # -- similarity_search --

    def test_similarity_search_aggregates_results(self):
        d1 = [_Doc("a"), _Doc("b")]
        d2 = [_Doc("c")]
        s1, s2 = _make_dummy_store(d1), _make_dummy_store(d2)

        results = vs.similarity_search([s1, s2], "q", k=10)
        assert len(results) == len(d1) + len(d2)

    # -- get_context_per_session --

    def test_get_context_per_session_returns_one_string_per_session(self):
        docs = [_Doc("alpha beta"), _Doc("gamma delta")]
        store = _make_dummy_store(docs)
        sid = "ctx-session"
        with vs._sessions_lock:
            vs._sessions[sid] = {"vectorstores": [store], "last_accessed": time.time()}

        contexts = vs.get_context_per_session([sid], query="q", k=10)
        assert len(contexts) == 1
        assert "alpha beta" in contexts[0]

    def test_get_context_skips_missing_sessions(self):
        contexts = vs.get_context_per_session(["ghost-session"])
        assert contexts == []
