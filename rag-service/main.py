from fastapi import FastAPI, Request, File, UploadFile
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


import os
import re
import uvicorn
import torch
import time
import threading
import logging
from transformers import (
    AutoConfig,
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    AutoModelForCausalLM,
)

from slowapi.errors import RateLimitExceeded
from uuid import uuid4
import os
import time
import uuid
import torch
import uvicorn

# IMPORTANT: Authentication REMOVED as per issue requirement
# (Authentication was breaking existing endpoints)


load_dotenv()


app = FastAPI()


app = FastAPI(
    title="PDF QA Bot API",
    description="PDF Question-Answering Bot (Session-based, No Auth)",
    version="2.1.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiter

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-base")
LLM_GENERATION_TIMEOUT = int(os.getenv("LLM_GENERATION_TIMEOUT", "30"))


# ===============================
# SESSION STORAGE (REQUIRED: keep sessionId)
# ===============================
# Format: { session_id: { "vectorstores": [FAISS], "last_accessed": float } }
sessions = {}

SESSION_TIMEOUT = 3600  # 1 hour
sessions = {}  # { session_id: { vectorstore, last_accessed } }

# -------------------------------------------------------------------
# MODELS
# -------------------------------------------------------------------
generation_tokenizer = None
generation_model = None
generation_is_encoder_decoder = False

# Embedding model (loaded once)
embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


# -------------------------------------------------------------------
# TEXT NORMALIZATION
# -------------------------------------------------------------------
def normalize_spaced_text(text: str) -> str:
    def fix(match):
        return match.group(0).replace(" ", "")

    pattern = r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b"
    return re.sub(pattern, fix, text)


def normalize_answer(text: str) -> str:
    text = normalize_spaced_text(text)
    text = re.sub(r"^(Answer[^:]*:|Context:|Question:)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# -------------------------------------------------------------------
# MODEL LOADING
# -------------------------------------------------------------------
def load_generation_model():
    global generation_tokenizer, generation_model, generation_is_encoder_decoder

    if generation_model and generation_tokenizer:
        return generation_tokenizer, generation_model, generation_is_encoder_decoder

    config = AutoConfig.from_pretrained(HF_GENERATION_MODEL)
    generation_is_encoder_decoder = bool(config.is_encoder_decoder)

    generation_tokenizer = AutoTokenizer.from_pretrained(HF_GENERATION_MODEL)

    if generation_is_encoder_decoder:
        generation_model = AutoModelForSeq2SeqLM.from_pretrained(HF_GENERATION_MODEL)
    else:
        generation_model = AutoModelForCausalLM.from_pretrained(HF_GENERATION_MODEL)

    if torch.cuda.is_available():
        generation_model = generation_model.to("cuda")

    generation_model.eval()

    return generation_tokenizer, generation_model, generation_is_encoder_decoder

# -------------------------------------------------------------------
# SAFE GENERATION WITH TIMEOUT
# -------------------------------------------------------------------
class TimeoutException(Exception):
    pass


def generate_with_timeout(model, encoded, max_new_tokens, pad_token_id, timeout):
    result = {"output": None, "error": None}

    def run():
        try:
            with torch.no_grad():
                result["output"] = model.generate(
                    **encoded,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=pad_token_id,
                )
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        raise TimeoutException("LLM generation timed out")

    if result["error"]:
        raise Exception(result["error"])

    return result["output"]


def generate_response(prompt: str, max_new_tokens: int) -> str:
    tokenizer, model, is_encoder_decoder = load_generation_model()
    device = next(model.parameters()).device

    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
    encoded = {k: v.to(device) for k, v in encoded.items()}

    pad_token_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    try:
        output_ids = generate_with_timeout(
            model, encoded, max_new_tokens, pad_token_id, LLM_GENERATION_TIMEOUT
        )
    except TimeoutException:
        raise HTTPException(status_code=504, detail="Model timed out")

    if is_encoder_decoder:
        return tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()

    input_len = encoded["input_ids"].shape[1]
    return tokenizer.decode(
        output_ids[0][input_len:], skip_special_tokens=True
    ).strip()

# ===============================
# LOAD GENERATION MODEL ONCE
# ===============================
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


# ===============================
# REQUEST MODELS

# -------------------------------------------------------------------
class PDFPath(BaseModel):
    filePath: str
    session_id: str

# ===============================
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_ids: list = []



class SummarizeRequest(BaseModel):
    session_ids: list = []


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str

    @validator("question")
    def validate_question(cls, v):
        if not v.strip():
            raise ValueError("Question cannot be empty")
        return v.strip()


class SummarizeRequest(BaseModel):
    session_id: str


class CompareRequest(BaseModel):
    session_ids: list = []


# ===============================
# UTILITIES
# ===============================
def cleanup_expired_sessions():
    current_time = time.time()
    expired = [
        sid for sid, data in sessions.items()
        if current_time - data["last_accessed"] > SESSION_TIMEOUT
    ]
    for sid in expired:
        del sessions[sid]


@app.post("/process-pdf")
@limiter.limit("15/15 minutes")
def process_pdf(request: Request, data: PDFPath):
    cleanup_expired_sessions()

    if not os.path.exists(data.filePath):
        raise HTTPException(status_code=404, detail="PDF not found")

    try:
        loader = PyPDFLoader(data.filePath)
        raw_docs = loader.load()

        cleaned_docs = [
            Document(
                page_content=normalize_spaced_text(doc.page_content),
                metadata=doc.metadata,
            )
            for doc in raw_docs
        ]

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
        )

        chunks = splitter.split_documents(cleaned_docs)

        if not chunks:
            raise HTTPException(status_code=400, detail="No text extracted from PDF")

        sessions[data.session_id] = {
            "vectorstore": FAISS.from_documents(chunks, embedding_model),
            "last_accessed": time.time(),
        }

        return {"message": "Document processed successfully"}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF processing failed: {str(e)}"
        )


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


# ===============================
# HEALTH ENDPOINTS (kept from enhancement branch)
# ===============================
@app.get("/healthz")
def health_check():
    return {"status": "healthy"}


@app.get("/readyz")
def readiness_check():
    return {"status": "ready"}


# ===============================
# UPLOAD (NO AUTH, RETURNS session_id)
# ===============================
@app.post("/upload")
@limiter.limit("10/15 minutes")
async def upload_file(request: Request, file: UploadFile = File(...)):
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
            "session_id": session_id
        }

    except Exception as e:
        return {"error": f"Upload failed: {str(e)}"}



# ===============================
# ASK (USES session_ids — matches fixed App.js)
# ===============================
@app.post("/ask")
@limiter.limit("60/15 minutes")
def ask_question(request: Request, data: AskRequest):
    cleanup_expired_sessions()


    session = sessions.get(data.session_id)
    if not session:
        return {"answer": "Session expired or PDF not uploaded"}

    session["last_accessed"] = time.time()
    vectorstore = session["vectorstore"]

    docs = vectorstore.similarity_search(data.question, k=4)
    if not docs:
        return {"answer": "No relevant context found."}

    context = "\n\n".join(doc.page_content for doc in docs)

    prompt = (
        "You are a helpful assistant answering ONLY from the context below.\n\n"

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


    answer = generate_response(prompt, max_new_tokens=256)

    answer = generate_response(prompt, 200)
    return {"answer": answer}


    return {"answer": normalize_answer(answer)}

# ===============================
# SUMMARIZE
# ===============================
@app.post("/summarize")
@limiter.limit("15/15 minutes")
def summarize_pdf(request: Request, data: SummarizeRequest):
    cleanup_expired_sessions()

    if not data.session_ids:
        return {"summary": "No session selected."}

    vectorstores = []
    for sid in data.session_ids:
        session = sessions.get(sid)
        if session:
            vectorstores.extend(session["vectorstores"])


    docs = vectorstore.similarity_search("Summarize the document.", k=6)
    if not docs:
        return {"summary": "No content available"}

    context = "\n\n".join(doc.page_content for doc in docs)

    prompt = (
        "Summarize the document in 6-8 concise bullet points.\n\n"
        f"Context:\n{context}\n\nSummary:"
    )

    summary = generate_response(prompt, max_new_tokens=220)

    if not vectorstores:
        return {"summary": "No documents found."}

    docs = []
    for vs in vectorstores:
        docs.extend(vs.similarity_search("Summarize the document", k=6))

    context = "\n\n".join([d.page_content for d in docs])

    prompt = f"Summarize this document:\n\n{context}\n\nSummary:"
    summary = generate_response(prompt, 250)

    return {"summary": summary}


    return {"summary": normalize_answer(summary)}

# ===============================
# COMPARE
# ===============================
@app.post("/compare")
@limiter.limit("10/15 minutes")
def compare_documents(request: Request, data: CompareRequest):
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


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000)