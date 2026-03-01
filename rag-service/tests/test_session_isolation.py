def test_session_vectorstores_are_isolated(client, test_pdf_file):
    # Upload first PDF
    with open(test_pdf_file, "rb") as f:
        r1 = client.post("/upload/anonymous", files={"file": ("a.pdf", f, "application/pdf")})
    assert r1.status_code == 200
    sid1 = r1.json().get("session_id")
    assert sid1

    # Upload second PDF (same file allowed for test)
    with open(test_pdf_file, "rb") as f2:
        r2 = client.post("/upload/anonymous", files={"file": ("b.pdf", f2, "application/pdf")})
    assert r2.status_code == 200
    sid2 = r2.json().get("session_id")
    assert sid2
    assert sid1 != sid2

    # Inspect in-memory session stores to ensure isolation
    from services.vector_service import _sessions
    assert sid1 in _sessions
    assert sid2 in _sessions

    vs1 = _sessions[sid1]["vectorstores"][0]
    vs2 = _sessions[sid2]["vectorstores"][0]

    # Instances must be different
    assert id(vs1) != id(vs2)

    # Their stored document objects should be distinct objects (no shared references)
    docs1 = vs1.similarity_search("anything", k=10)
    docs2 = vs2.similarity_search("anything", k=10)
    # Guard against false positives: both searches must return some results
    assert docs1, "Expected non-empty search results for first session"
    assert docs2, "Expected non-empty search results for second session"
    ids1 = {id(d) for d in docs1}
    ids2 = {id(d) for d in docs2}
    assert ids1.isdisjoint(ids2)
