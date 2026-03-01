import pytest


def test_upload_and_session_flow(client, test_pdf_file):
    # Upload a PDF and expect a session_id returned
    with open(test_pdf_file, "rb") as f:
        resp = client.post(
            "/upload/anonymous",
            files={"file": ("test.pdf", f, "application/pdf")}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    session_id = data["session_id"]

    # Ask using the session_id
    ask_payload = {"question": "What is this document about?", "session_ids": [session_id]}
    resp2 = client.post("/ask", json=ask_payload)
    assert resp2.status_code == 200
    ans = resp2.json().get("answer")
    assert isinstance(ans, str)

    # Summarize using the session_id
    resp3 = client.post("/summarize", json={"session_ids": [session_id]})
    assert resp3.status_code == 200
    assert "summary" in resp3.json()

    # Upload another PDF to create a second session for compare
    with open(test_pdf_file, "rb") as f2:
        resp4 = client.post(
            "/upload",
            files={"file": ("test2.pdf", f2, "application/pdf")}
        )

    assert resp4.status_code == 200
    sid2 = resp4.json().get("session_id")
    assert sid2

    # Compare the two sessions
    resp5 = client.post("/compare", json={"session_ids": [session_id, sid2]})
    assert resp5.status_code == 200
    assert "comparison" in resp5.json()
