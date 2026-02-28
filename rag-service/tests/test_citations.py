"""
Tests for PDF page-level citation feature.

Validates that:
- /ask returns a `citations` list alongside the answer
- Page numbers are 1-indexed (PyPDFLoader is 0-indexed)
- Citations are deduplicated (same page from same doc only once)
- Citations are sorted by source then page number
- No session / empty session returns citations: []
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from langchain_core.documents import Document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_doc(content: str, page: int, source: str = "test.pdf") -> Document:
    """Create a Document with PyPDFLoader-style metadata (0-indexed page)."""
    return Document(page_content=content, metadata={"page": page, "source": source})


def make_session(docs: list[Document], filename: str = "test.pdf"):
    """Build a fake session dict with a mocked vectorstore."""
    mock_vs = MagicMock()
    mock_vs.similarity_search.return_value = docs

    import time
    return {
        "vectorstores": [mock_vs],
        "filename": filename,
        "last_accessed": time.time(),
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """TestClient with model and embeddings mocked out (no GPU/model needed)."""
    with (
        patch("main.embedding_model"),
        patch("main.model"),
        patch("main.tokenizer"),
        patch("main.generate_response", return_value="Mocked answer"),
    ):
        from main import app
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCitationsInAskEndpoint:

    def test_ask_returns_citations_field(self, client):
        """Response must always include a `citations` key."""
        from main import sessions
        sid = "sid-001"
        sessions[sid] = make_session([make_doc("Some text about topic A.", page=2)])

        response = client.post("/ask", json={
            "question": "What is topic A?",
            "session_ids": [sid]
        })

        assert response.status_code == 200
        body = response.json()
        assert "citations" in body

    def test_page_numbers_are_one_indexed(self, client):
        """PyPDFLoader returns page=0 for the first page; we must expose page=1."""
        from main import sessions
        sid = "sid-002"
        # page=0 in metadata → should come back as page=1 in citation
        sessions[sid] = make_session([make_doc("First page content.", page=0)])

        response = client.post("/ask", json={
            "question": "What is on the first page?",
            "session_ids": [sid]
        })

        body = response.json()
        pages = [c["page"] for c in body["citations"]]
        assert 1 in pages, f"Expected page 1 (1-indexed) but got: {pages}"

    def test_citations_deduplicated(self, client):
        """Multiple chunks from the same page must produce one citation entry."""
        from main import sessions
        sid = "sid-003"
        # Two different chunks both on page 4 (0-indexed: 3)
        docs = [
            make_doc("Chunk A of page 5.", page=4),
            make_doc("Chunk B of page 5.", page=4),
        ]
        sessions[sid] = make_session(docs)

        response = client.post("/ask", json={
            "question": "What is on page 5?",
            "session_ids": [sid]
        })

        body = response.json()
        pages = [c["page"] for c in body["citations"]]
        # Page 5 should appear only once
        assert pages.count(5) == 1

    def test_citations_sorted_by_source_then_page(self, client):
        """Citations must be sorted: first by source filename, then by page."""
        from main import sessions

        sid_a = "sid-004a"
        sid_b = "sid-004b"
        sessions[sid_a] = make_session(
            [make_doc("B doc page 3 text", page=2), make_doc("B doc page 1 text", page=0)],
            filename="b_doc.pdf"
        )
        sessions[sid_b] = make_session(
            [make_doc("A doc page 2 text", page=1)],
            filename="a_doc.pdf"
        )

        response = client.post("/ask", json={
            "question": "What are the main topics?",
            "session_ids": [sid_a, sid_b]
        })

        body = response.json()
        sources = [c["source"] for c in body["citations"]]
        pages = [c["page"] for c in body["citations"]]

        # a_doc.pdf should come before b_doc.pdf
        a_indices = [i for i, s in enumerate(sources) if s == "a_doc.pdf"]
        b_indices = [i for i, s in enumerate(sources) if s == "b_doc.pdf"]
        assert a_indices, "a_doc.pdf not in citations"
        assert b_indices, "b_doc.pdf not in citations"
        assert max(a_indices) < min(b_indices), "a_doc.pdf citations should appear before b_doc.pdf"

        # Within b_doc.pdf, page 1 before page 3
        b_pages = [pages[i] for i in b_indices]
        assert b_pages == sorted(b_pages)

    def test_no_session_returns_empty_citations(self, client):
        """Empty session_ids should return citations: []."""
        response = client.post("/ask", json={
            "question": "Anything?",
            "session_ids": []
        })

        body = response.json()
        assert "citations" in body
        assert body["citations"] == []

    def test_invalid_session_returns_empty_citations(self, client):
        """A session_id that does not exist should return citations: []."""
        response = client.post("/ask", json={
            "question": "Anything?",
            "session_ids": ["nonexistent-session-id"]
        })

        body = response.json()
        assert "citations" in body
        assert body["citations"] == []

    def test_citation_source_matches_uploaded_filename(self, client):
        """The `source` field in citations must match the original filename."""
        from main import sessions
        sid = "sid-006"
        sessions[sid] = make_session(
            [make_doc("Some content.", page=0)],
            filename="annual_report_2025.pdf"
        )

        response = client.post("/ask", json={
            "question": "What does the report say?",
            "session_ids": [sid]
        })

        body = response.json()
        assert len(body["citations"]) > 0
        assert body["citations"][0]["source"] == "annual_report_2025.pdf"

    def test_multiple_documents_all_cited(self, client):
        """When asking across 2 PDFs, both should appear in citations."""
        from main import sessions

        sid_x = "sid-007x"
        sid_y = "sid-007y"
        sessions[sid_x] = make_session(
            [make_doc("Doc X content.", page=0)],
            filename="doc_x.pdf"
        )
        sessions[sid_y] = make_session(
            [make_doc("Doc Y content.", page=1)],
            filename="doc_y.pdf"
        )

        response = client.post("/ask", json={
            "question": "Compare the documents.",
            "session_ids": [sid_x, sid_y]
        })

        body = response.json()
        sources = {c["source"] for c in body["citations"]}
        assert "doc_x.pdf" in sources
        assert "doc_y.pdf" in sources
