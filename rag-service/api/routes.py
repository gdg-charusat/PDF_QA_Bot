"""
api/routes.py
~~~~~~~~~~~~~
FastAPI ``APIRouter`` containing all application endpoints.

Route handlers are intentionally thin: they validate HTTP concerns (file type,
missing sessions, etc.) and delegate all business logic to the service layer.
"""

import logging
import os
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from core.config import UPLOAD_DIR, limiter
from models.schemas import AskRequest, CompareRequest, SummarizeRequest
from services.llm_service import generate_response
from services.vector_service import (
    cleanup_expired_sessions,
    create_session_from_file,
    get_context_per_session,
    get_vectorstores_for_sessions,
    similarity_search,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@router.get("/healthz", tags=["health"])
def health_check():
    """Liveness probe."""
    return {"status": "healthy"}


@router.get("/readyz", tags=["health"])
def readiness_check():
    """Readiness probe."""
    return {"status": "ready"}


@router.get("/health", tags=["health"])
def health():
    """Legacy health endpoint kept for backward compatibility."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def _handle_upload(file: UploadFile) -> tuple[str, str]:
    """Validate the uploaded file and return ``(filename, destination_path)``."""
    filename = os.path.basename(file.filename or "")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, f"{uuid4().hex}_{filename}")
    return filename, file_path


async def _do_upload(file: UploadFile) -> dict:
    """Core upload logic shared by /upload and /upload/anonymous."""
    filename, file_path = _handle_upload(file)
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        session_id = create_session_from_file(file_path)
        return {"message": "PDF uploaded and processed", "session_id": session_id}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Upload failed for file '%s'", filename)
        # best-effort cleanup if create_session_from_file hasn't deleted it yet
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Upload failed")


@router.post("/upload", tags=["documents"])
@limiter.limit("10/15 minutes")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """Upload a PDF, process it, and return a session ID."""
    return await _do_upload(file)


@router.post("/upload/anonymous", tags=["documents"])
@limiter.limit("10/15 minutes")
async def upload_anonymous(request: Request, file: UploadFile = File(...)):
    """Anonymous upload endpoint – identical behaviour to /upload."""
    return await _do_upload(file)


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------
@router.post("/ask", tags=["qa"])
@limiter.limit("60/15 minutes")
def ask_question(request: Request, data: AskRequest):
    """Answer a question using the documents in the given sessions."""
    cleanup_expired_sessions()

    if not data.session_ids:
        return {"answer": "No session selected."}

    vectorstores = get_vectorstores_for_sessions(data.session_ids)
    if not vectorstores:
        return {"answer": "No documents found for selected sessions."}

    docs = similarity_search(vectorstores, data.question, k=4)
    if not docs:
        return {"answer": "No relevant context found."}

    context = "\n\n".join(d.page_content for d in docs)
    prompt = (
        "Answer the question using ONLY the provided context.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {data.question}\nAnswer:"
    )

    try:
        answer = generate_response(prompt, max_new_tokens=200)
        return {"answer": answer}
    except RuntimeError as exc:
        logger.warning("Generation unavailable: %s", exc)
        return JSONResponse(status_code=503, content={"answer": None, "error": str(exc)})
    except Exception:
        logger.exception("Generation failed")
        return JSONResponse(
            status_code=500, content={"answer": None, "error": "Generation failed"}
        )


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------
@router.post("/summarize", tags=["qa"])
@limiter.limit("15/15 minutes")
def summarize_pdf(request: Request, data: SummarizeRequest):
    """Return a summary of the documents associated with the given sessions."""
    cleanup_expired_sessions()

    if not data.session_ids:
        return {"summary": "No session selected."}

    vectorstores = get_vectorstores_for_sessions(data.session_ids)
    if not vectorstores:
        return {"summary": "No documents found."}

    docs = similarity_search(vectorstores, "Summarize the document", k=6)
    context = "\n\n".join(d.page_content for d in docs)
    prompt = f"Summarize this document:\n\n{context}\n\nSummary:"

    try:
        summary = generate_response(prompt, max_new_tokens=250)
        return {"summary": summary}
    except RuntimeError as exc:
        logger.warning("Generation unavailable: %s", exc)
        return JSONResponse(
            status_code=503, content={"summary": None, "error": str(exc)}
        )
    except Exception:
        logger.exception("Generation failed")
        return JSONResponse(
            status_code=500, content={"summary": None, "error": "Generation failed"}
        )


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------
@router.post("/compare", tags=["qa"])
@limiter.limit("10/15 minutes")
def compare_documents(request: Request, data: CompareRequest):
    """Compare documents across two or more sessions."""
    cleanup_expired_sessions()

    if len(data.session_ids) < 2:
        return {"comparison": "Select at least 2 documents."}

    contexts = get_context_per_session(data.session_ids, query="main topics", k=4)

    if len(contexts) < 2:
        return {"comparison": "Not enough documents to compare."}

    combined = "\n\n---\n\n".join(contexts)
    prompt = (
        "Compare the documents below.\n"
        "Give similarities and differences.\n\n"
        f"{combined}\n\nComparison:"
    )

    try:
        comparison = generate_response(prompt, max_new_tokens=300)
        return {"comparison": comparison}
    except RuntimeError as exc:
        logger.warning("Generation unavailable: %s", exc)
        return JSONResponse(
            status_code=503, content={"comparison": None, "error": str(exc)}
        )
    except Exception:
        logger.exception("Generation failed")
        return JSONResponse(
            status_code=500, content={"comparison": None, "error": "Generation failed"}
        )
