"""
Unit tests for services/document_service.py

These tests run without torch, transformers, or FAISS — only the
document-loading and chunking logic is exercised.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeDoc:
    """Minimal stand-in for a LangChain Document."""

    def __init__(self, text: str):
        self.page_content = text


# ---------------------------------------------------------------------------
# load_pdf
# ---------------------------------------------------------------------------

class TestLoadPdf:
    def test_uses_langchain_loader_when_available(self, tmp_path):
        """When PyPDFLoader is importable, it should be used and its result returned."""
        fake_docs = [_FakeDoc("page one"), _FakeDoc("page two")]
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = fake_docs
        mock_loader_cls = MagicMock(return_value=mock_loader_instance)

        with patch("services.document_service._PyPDFLoader", mock_loader_cls):
            from services.document_service import load_pdf

            # Reset cached loader so our mock is picked up
            import services.document_service as ds
            original = ds._PyPDFLoader
            ds._PyPDFLoader = mock_loader_cls

            pdf = tmp_path / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4 fake")
            result = ds.load_pdf(str(pdf))

        ds._PyPDFLoader = original  # restore
        assert result == fake_docs

    def test_fallback_to_pypdf_when_langchain_absent(self, tmp_path):
        """When _PyPDFLoader is None, load_pdf should fall back to pypdf."""
        import services.document_service as ds

        # Build a real minimal PDF so pypdf can open it
        pdf_content = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
            b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
            b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]>>\nendobj\n"
            b"xref\n0 4\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"trailer\n<</Size 4 /Root 1 0 R>>\nstartxref\n179\n%%EOF"
        )
        pdf_path = tmp_path / "fallback.pdf"
        pdf_path.write_bytes(pdf_content)

        saved = ds._PyPDFLoader
        ds._PyPDFLoader = None  # force fallback path
        try:
            docs = ds.load_pdf(str(pdf_path))
        finally:
            ds._PyPDFLoader = saved

        assert isinstance(docs, list)
        # Each item must expose page_content
        for doc in docs:
            assert hasattr(doc, "page_content")


# ---------------------------------------------------------------------------
# chunk_documents
# ---------------------------------------------------------------------------

class TestChunkDocuments:
    def test_splits_large_doc_into_multiple_chunks(self):
        """A doc larger than chunk_size should be split (uses a real or mocked splitter)."""
        import services.document_service as ds

        big_text = "word " * 300  # ~1500 chars
        docs = [_FakeDoc(big_text)]

        if ds._RecursiveCharacterTextSplitter is None:
            # Splitter not available in this environment — mock it
            class _FakeSplitter:
                def __init__(self, chunk_size, chunk_overlap):
                    self._size = chunk_size

                def split_documents(self, docs):
                    result = []
                    for doc in docs:
                        text = doc.page_content
                        for i in range(0, len(text), self._size):
                            result.append(_FakeDoc(text[i : i + self._size]))
                    return result

            saved = ds._RecursiveCharacterTextSplitter
            ds._RecursiveCharacterTextSplitter = _FakeSplitter
            try:
                chunks = ds.chunk_documents(docs, chunk_size=200, chunk_overlap=20)
            finally:
                ds._RecursiveCharacterTextSplitter = saved
        else:
            chunks = ds.chunk_documents(docs, chunk_size=200, chunk_overlap=20)

        assert len(chunks) > 1

    def test_small_doc_fits_in_one_chunk(self):
        """A doc smaller than chunk_size should not be split."""
        import services.document_service as ds

        docs = [_FakeDoc("short")]
        chunks = ds.chunk_documents(docs, chunk_size=1000, chunk_overlap=100)
        assert len(chunks) == 1

    def test_fallback_returns_docs_unchanged_when_splitter_absent(self):
        """When _RecursiveCharacterTextSplitter is None, original docs are returned."""
        import services.document_service as ds

        docs = [_FakeDoc("a" * 5000)]
        saved = ds._RecursiveCharacterTextSplitter
        ds._RecursiveCharacterTextSplitter = None
        try:
            result = ds.chunk_documents(docs)
        finally:
            ds._RecursiveCharacterTextSplitter = saved

        assert result is docs
