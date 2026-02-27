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
from slowapi.errors import RateLimitExceeded
from uuid import uuid4
import os
import time
import uuid
import torch
import uvicorn
import pdf2image
import pytesseract
from PIL import Image

# Post-processing helpers: strip prompt echoes / context leakage from LLM output
# so that the API always returns only the clean, user-facing answer/summary/comparison.
from utils.postprocess import extract_final_answer, extract_final_summary, extract_comparison

# Centralised minimal prompt builders (short prompts → less instruction echoing).
from utils.prompt_templates import build_ask_prompt, build_summarize_prompt, build_compare_prompt

load_dotenv()

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

# ===============================
# SESSION STORAGE (REQUIRED: keep sessionId)
# ===============================
# Format: { session_id: { "vectorstores": [FAISS], "last_accessed": float } }
sessions = {}
SESSION_TIMEOUT = 3600  # 1 hour

# Embedding model (loaded once)
embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

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
# ===============================
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_ids: list = []


class SummarizeRequest(BaseModel):
    session_ids: list = []


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

        # Check if each page has extractable text
        final_docs = []
        images = None
        
        for i, doc in enumerate(docs):
            if len(doc.page_content.strip()) < 50:
                # Fallback to OCR for this specific page
                if images is None:
                    print("Low text content detected on one or more pages. Falling back to OCR...")
                    images = pdf2image.convert_from_path(file_path)
                
                if i < len(images):
                    ocr_text = pytesseract.image_to_string(images[i])
                    final_docs.append(Document(
                        page_content=ocr_text,
                        metadata={"source": file_path, "page": i}
                    ))
                else:
                    final_docs.append(doc)
            else:
                final_docs.append(doc)

        docs = final_docs

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100
        )
        chunks = splitter.split_documents(docs)

        if not chunks:
            return {"error": "Upload failed: No extractable text found in the document (OCR yielded nothing)."}

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

    # ── Build minimal prompt via prompt_templates (reduces instruction echoing) ──
    prompt = build_ask_prompt(
        context=context,
        question=question,
        conversation_context=conversation_context,
    )

    raw_answer = generate_response(prompt, max_new_tokens=150)
    # Post-process: strip any leaked prompt/context text; return clean answer only.
    clean_answer = extract_final_answer(raw_answer)
    return {"answer": clean_answer}


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

    if not vectorstores:
        return {"summary": "No documents found."}

    docs = []
    for vs in vectorstores:
        docs.extend(vs.similarity_search("Summarize the document", k=6))

    context = "\n\n".join([d.page_content for d in docs])

    # ── Build minimal summarization prompt ───────────────────────────────────
    prompt = build_summarize_prompt(context=context)

    raw_summary = generate_response(prompt, max_new_tokens=300)
    # Post-process: strip any leaked prompt/context text from the summary.
    summary = extract_final_summary(raw_summary)
    return {"summary": summary}


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

    # Retrieve top chunks from each document separately for fair comparison
    query = "summarize the main topic, purpose, and key details of this document"
    per_doc_contexts = []
    for i, vs in enumerate(vectorstores):
        chunks = vs.similarity_search(query, k=4)
        text = "\n".join([c.page_content for c in chunks])
        per_doc_contexts.append(text)

    # ── Build minimal comparison prompt ───────────────────────────────────────
    prompt = build_compare_prompt(per_doc_contexts=per_doc_contexts)

    raw = generate_response(prompt, max_new_tokens=400)
    # Post-process: strip any leaked prompt/context text from the comparison.
    comparison = extract_comparison(raw)
    return {"comparison": comparison}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000)