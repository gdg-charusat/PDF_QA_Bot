import os
import pytest
from fastapi.testclient import TestClient
from rag-service.main import app

client = TestClient(app)

def test_upload_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), "test.pdf")
    # Create a dummy PDF file for testing
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4 test pdf content\n%%EOF")
    with open(pdf_path, "rb") as f:
        response = client.post("/upload", files={"file": ("test.pdf", f, "application/pdf")})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["message"] == "PDF uploaded and processed"
    os.remove(pdf_path)

def test_upload_non_pdf():
    txt_path = os.path.join(os.path.dirname(__file__), "test.txt")
    with open(txt_path, "w") as f:
        f.write("not a pdf")
    with open(txt_path, "rb") as f:
        response = client.post("/upload", files={"file": ("test.txt", f, "text/plain")})
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
    os.remove(txt_path)
