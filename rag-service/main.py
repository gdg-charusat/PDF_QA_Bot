from fastapi import FastAPI, Request, File, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document
from dotenv import load_dotenv
from transformers import AutoConfig, AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from uuid import uuid4
import os
import time
import uuid
import torch
import uvicorn

# ── Authentication ─────────────────────────────────────────────────────────────
from database import Base, engine, get_db
from auth.router import router as auth_router
from auth.middleware import (
    get_current_user,
    require_upload_permission,
    require_ask_permission,
    require_summarize_permission,
    require_compare_permission,
)
from auth.models import User

load_dotenv()

# Create database tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PDF QA Bot API",
    description=(
        "PDF Question-Answering Bot with JWT Authentication and Role-Based Access Control. "
        "All PDF processing endpoints require a valid Bearer token. "
        "Register at /auth/register and login at /auth/login to obtain a token."
    ),
    version="2.2.0"
)

# ── Include auth router ────────────────────────────────────────────────────────
app.include_router(auth_router)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Session Storage ────────────────────────────────────────────────────────────
# Format: { session_id: { "vectorstores": [FAISS], "last_accessed": float } }
sessions = {}
SESSION_TIMEOUT = 3600  # 1 hour

# ── Embedding model (loaded once) ──────────────────────────────────────────────
embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# ── Generation model ───────────────────────────────────────────────────────────
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-small")

config = AutoConfig.from_pretrained(HF_GENERATION_MODEL)
is_encoder_decoder = bool(getattr(config, "is_encoder_decoder", False))
tokenizer = AutoTokenizer.from_pretrained(HF_GENERATION_MODEL)

if is_encoder_decoder:
    model = AutoModelForSeq2SeqLM.from_pretrained(HF_GENERATION_MODEL)
else:
    model = AutoModelForCausalLM.from_pretrained(HF_GENERATION_MODEL)

if torch.cuda.is_available():
    model = model.to("cuda")

model.eval()

# ── Request models ─────────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_ids: list = []


class SummarizeRequest(BaseModel):
    session_ids: list = []


class CompareRequest(BaseModel):
    session_ids: list = []


# ── Utilities ──────────────────────────────────────────────────────────────────
def cleanup_expired_sessions():
    current_time = time.time()
    expired = [
        sid for sid, data in sessions.items()
        if current_time - data["last_accessed"] > SESSION_TIMEOUT
    ]
    for sid in expired:
        del sessions[sid]


def generate_response(prompt: str, max_new_tokens: int = 200) -> str:
    device = next(model.parameters()).device
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
    inputs = {k: v.to(device) for k, v in inputs.items()}

    output = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
    )

    if is_encoder_decoder:
        return tokenizer.decode(output[0], skip_special_tokens=True)

    return tokenizer.decode(
        output[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )


# ── Health Endpoints (public — no auth required) ───────────────────────────────
@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "healthy"}


@app.get("/readyz", tags=["Health"])
def readiness_check():
    return {"status": "ready"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


# ── Upload (🔐 Requires auth — upload_pdf permission) ──────────────────────────
@app.post("/upload", tags=["PDF Processing"])
@limiter.limit("10/15 minutes")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_upload_permission),
):
    """
    Upload and process a PDF file. Returns a session_id used for subsequent
    /ask, /summarize, and /compare requests.

    Requires authentication. User role requires 'upload_pdf' permission.
    """
    if not file.filename.lower().endswith(".pdf"):
        return {"error": "Only PDF files are supported"}

    session_id = str(uuid4())
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{uuid4().hex}_{file.filename}")

    try:
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        loader = PyPDFLoader(file_path)
        docs = loader.load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100
        )
        chunks = splitter.split_documents(docs)

        vectorstore = FAISS.from_documents(chunks, embedding_model)

        sessions[session_id] = {
            "vectorstores": [vectorstore],
            "last_accessed": time.time()
        }

        return {
            "message": "PDF uploaded and processed",
            "session_id": session_id,
            "uploaded_by": current_user.username,
        }

    except Exception as e:
        return {"error": f"Upload failed: {str(e)}"}


# ── Ask (🔐 Requires auth — ask_question permission) ───────────────────────────
@app.post("/ask", tags=["PDF Processing"])
@limiter.limit("60/15 minutes")
def ask_question(
    request: Request,
    data: AskRequest,
    current_user: User = Depends(require_ask_permission),
):
    """
    Ask a question about one or more uploaded PDFs identified by session_ids.

    Requires authentication. User role requires 'ask_question' permission.
    """
    cleanup_expired_sessions()

    if not data.session_ids:
        return {"answer": "No session selected."}

    vectorstores = []
    for sid in data.session_ids:
        session = sessions.get(sid)
        if session:
            session["last_accessed"] = time.time()
            vectorstores.extend(session["vectorstores"])

    if not vectorstores:
        return {"answer": "No documents found for selected sessions."}

    docs = []
    for vs in vectorstores:
        docs.extend(vs.similarity_search(data.question, k=4))

    if not docs:
        return {"answer": "No relevant context found."}

    context = "\n\n".join([d.page_content for d in docs])

    prompt = (
        "Answer the question using ONLY the provided context.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {data.question}\nAnswer:"
    )

    answer = generate_response(prompt, 200)
    return {"answer": answer}


# ── Summarize (🔐 Requires auth — summarize permission) ────────────────────────
@app.post("/summarize", tags=["PDF Processing"])
@limiter.limit("15/15 minutes")
def summarize_pdf(
    request: Request,
    data: SummarizeRequest,
    current_user: User = Depends(require_summarize_permission),
):
    """
    Summarize one or more uploaded PDFs identified by session_ids.

    Requires authentication. User role requires 'summarize' permission.
    """
    cleanup_expired_sessions()

    if not data.session_ids:
        return {"summary": "No session selected."}

    vectorstores = []
    for sid in data.session_ids:
        session = sessions.get(sid)
        if session:
            vectorstores.extend(session["vectorstores"])

    if not vectorstores:
        return {"summary": "No documents found."}

    docs = []
    for vs in vectorstores:
        docs.extend(vs.similarity_search("Summarize the document", k=6))

    context = "\n\n".join([d.page_content for d in docs])

    prompt = f"Summarize this document:\n\n{context}\n\nSummary:"
    summary = generate_response(prompt, 250)

    return {"summary": summary}


# ── Compare (🔐 Requires auth — compare_documents permission / admin only) ──────
@app.post("/compare", tags=["PDF Processing"])
@limiter.limit("10/15 minutes")
def compare_documents(
    request: Request,
    data: CompareRequest,
    current_user: User = Depends(require_compare_permission),
):
    """
    Compare two or more uploaded PDFs identified by session_ids.

    Requires authentication. Admin role required ('compare_documents' permission).
    """
    cleanup_expired_sessions()

    if len(data.session_ids) < 2:
        return {"comparison": "Select at least 2 documents."}

    contexts = []
    for sid in data.session_ids:
        session = sessions.get(sid)
        if session:
            vs = session["vectorstores"][0]
            chunks = vs.similarity_search("main topics", k=4)
            text = "\n".join([c.page_content for c in chunks])
            contexts.append(text)

    if len(contexts) < 2:
        return {"comparison": "Not enough documents to compare."}

    combined = "\n\n---\n\n".join(contexts)

    prompt = (
        "Compare the documents below.\n"
        "Give similarities and differences.\n\n"
        f"{combined}\n\nComparison:"
    )

    comparison = generate_response(prompt, 300)
    return {"comparison": comparison}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000)