"""
Integration tests for api/routes.py

Every service call is mocked so the tests exercise only the HTTP layer:
status codes, request/response shapes, and rate-limit wiring.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

class TestHealthEndpoints:
    def test_healthz(self):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "healthy"}

    def test_readyz(self):
        r = client.get("/readyz")
        assert r.status_code == 200
        assert r.json() == {"status": "ready"}

    def test_health_legacy(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Upload endpoints
# ---------------------------------------------------------------------------

class TestUploadEndpoints:
    _PDF_BYTES = (
        b"%PDF-1.4\n1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
        b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
        b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]>>\nendobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer\n<</Size 4 /Root 1 0 R>>\nstartxref\n179\n%%EOF"
    )

    def _upload(self, endpoint: str, filename: str = "test.pdf"):
        with patch("api.routes.create_session_from_file", return_value="mock-session-id"):
            return client.post(
                endpoint,
                files={"file": (filename, self._PDF_BYTES, "application/pdf")},
            )

    def test_upload_returns_session_id(self):
        r = self._upload("/upload")
        assert r.status_code == 200
        assert r.json()["session_id"] == "mock-session-id"

    def test_upload_anonymous_returns_session_id(self):
        r = self._upload("/upload/anonymous")
        assert r.status_code == 200
        assert r.json()["session_id"] == "mock-session-id"

    def test_upload_rejects_non_pdf(self):
        r = client.post(
            "/upload",
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        )
        assert r.status_code == 400
        assert "PDF" in r.json()["detail"]

    def test_upload_anonymous_rejects_non_pdf(self):
        r = client.post(
            "/upload/anonymous",
            files={"file": ("data.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 400

    def test_upload_returns_500_on_processing_error(self):
        with patch("api.routes.create_session_from_file", side_effect=RuntimeError("boom")):
            r = client.post(
                "/upload",
                files={"file": ("test.pdf", self._PDF_BYTES, "application/pdf")},
            )
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# /ask
# ---------------------------------------------------------------------------

class TestAskEndpoint:
    def test_returns_answer_when_sessions_present(self):
        mock_store = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "The sky is blue."
        mock_store.similarity_search.return_value = [mock_doc]

        with (
            patch("api.routes.cleanup_expired_sessions"),
            patch("api.routes.get_vectorstores_for_sessions", return_value=[mock_store]),
            patch("api.routes.similarity_search", return_value=[mock_doc]),
            patch("api.routes.generate_response", return_value="Because Rayleigh scattering."),
        ):
            r = client.post("/ask", json={"question": "Why is the sky blue?", "session_ids": ["s1"]})

        assert r.status_code == 200
        assert r.json()["answer"] == "Because Rayleigh scattering."

    def test_returns_no_session_message_when_empty(self):
        with patch("api.routes.cleanup_expired_sessions"):
            r = client.post("/ask", json={"question": "anything", "session_ids": []})
        assert r.status_code == 200
        assert r.json()["answer"] == "No session selected."

    def test_returns_no_documents_when_sessions_unknown(self):
        with (
            patch("api.routes.cleanup_expired_sessions"),
            patch("api.routes.get_vectorstores_for_sessions", return_value=[]),
        ):
            r = client.post("/ask", json={"question": "q", "session_ids": ["ghost"]})
        assert r.status_code == 200
        assert "No documents" in r.json()["answer"]

    def test_returns_503_when_model_unavailable(self):
        mock_doc = MagicMock()
        mock_doc.page_content = "Context."

        with (
            patch("api.routes.cleanup_expired_sessions"),
            patch("api.routes.get_vectorstores_for_sessions", return_value=[MagicMock()]),
            patch("api.routes.similarity_search", return_value=[mock_doc]),
            patch("api.routes.generate_response", side_effect=RuntimeError("Generation model unavailable")),
        ):
            r = client.post("/ask", json={"question": "q", "session_ids": ["s1"]})

        assert r.status_code == 503
        assert r.json()["answer"] is None

    def test_rejects_empty_question(self):
        r = client.post("/ask", json={"question": "", "session_ids": ["s1"]})
        assert r.status_code == 422  # Pydantic min_length validation


# ---------------------------------------------------------------------------
# /summarize
# ---------------------------------------------------------------------------

class TestSummarizeEndpoint:
    def test_returns_summary(self):
        mock_doc = MagicMock()
        mock_doc.page_content = "Important content."

        with (
            patch("api.routes.cleanup_expired_sessions"),
            patch("api.routes.get_vectorstores_for_sessions", return_value=[MagicMock()]),
            patch("api.routes.similarity_search", return_value=[mock_doc]),
            patch("api.routes.generate_response", return_value="A concise summary."),
        ):
            r = client.post("/summarize", json={"session_ids": ["s1"]})

        assert r.status_code == 200
        assert r.json()["summary"] == "A concise summary."

    def test_returns_no_session_message_when_empty(self):
        with patch("api.routes.cleanup_expired_sessions"):
            r = client.post("/summarize", json={"session_ids": []})
        assert r.status_code == 200
        assert r.json()["summary"] == "No session selected."

    def test_returns_503_when_model_unavailable(self):
        mock_doc = MagicMock()
        mock_doc.page_content = "x"

        with (
            patch("api.routes.cleanup_expired_sessions"),
            patch("api.routes.get_vectorstores_for_sessions", return_value=[MagicMock()]),
            patch("api.routes.similarity_search", return_value=[mock_doc]),
            patch("api.routes.generate_response", side_effect=RuntimeError("unavailable")),
        ):
            r = client.post("/summarize", json={"session_ids": ["s1"]})

        assert r.status_code == 503


# ---------------------------------------------------------------------------
# /compare
# ---------------------------------------------------------------------------

class TestCompareEndpoint:
    def test_returns_comparison_for_two_sessions(self):
        with (
            patch("api.routes.cleanup_expired_sessions"),
            patch("api.routes.get_context_per_session", return_value=["ctx A", "ctx B"]),
            patch("api.routes.generate_response", return_value="Both talk about AI."),
        ):
            r = client.post("/compare", json={"session_ids": ["s1", "s2"]})

        assert r.status_code == 200
        assert r.json()["comparison"] == "Both talk about AI."

    def test_requires_at_least_two_sessions(self):
        with patch("api.routes.cleanup_expired_sessions"):
            r = client.post("/compare", json={"session_ids": ["only-one"]})
        assert r.status_code == 200
        assert "at least 2" in r.json()["comparison"]

    def test_handles_insufficient_context(self):
        with (
            patch("api.routes.cleanup_expired_sessions"),
            patch("api.routes.get_context_per_session", return_value=["only one context"]),
        ):
            r = client.post("/compare", json={"session_ids": ["s1", "s2"]})
        assert r.status_code == 200
        assert "Not enough" in r.json()["comparison"]

    def test_returns_503_when_model_unavailable(self):
        with (
            patch("api.routes.cleanup_expired_sessions"),
            patch("api.routes.get_context_per_session", return_value=["ctx A", "ctx B"]),
            patch("api.routes.generate_response", side_effect=RuntimeError("unavailable")),
        ):
            r = client.post("/compare", json={"session_ids": ["s1", "s2"]})
        assert r.status_code == 503
