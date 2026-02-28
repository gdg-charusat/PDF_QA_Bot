from fastapi import FastAPI, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from uuid import uuid4
import os
import time
import uuid
import threading
import json
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
# SESSION STORAGE — per-session, no shared global vectorstore
# ===============================
# Format: { session_id: { "vectorstores": [FAISS], "last_accessed": float } }
# Guard with a lock so concurrent requests never corrupt the dict.
sessions: dict = {}
_session_lock = threading.Lock()
SESSION_TIMEOUT = 3600  # 1 hour

# Embedding model (loaded once — None if sentence-transformers is unavailable)\ntry:\n    embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")\nexcept Exception:  # pragma: no cover\n    embedding_model = None

# ===============================
# GENERATION MODEL — loaded lazily; stays None when transformers unavailable
# ===============================
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-small")

_model = None
_tokenizer = None
_is_encoder_decoder = False

try:
    import torch
    from transformers import (
        AutoConfig,
        AutoTokenizer,
        AutoModelForSeq2SeqLM,
        AutoModelForCausalLM,
        TextIteratorStreamer,
    )
    _cfg = AutoConfig.from_pretrained(HF_GENERATION_MODEL)
    _is_encoder_decoder = bool(getattr(_cfg, "is_encoder_decoder", False))
    _tokenizer = AutoTokenizer.from_pretrained(HF_GENERATION_MODEL)
    if _is_encoder_decoder:
        _model = AutoModelForSeq2SeqLM.from_pretrained(HF_GENERATION_MODEL)
    else:
        _model = AutoModelForCausalLM.from_pretrained(HF_GENERATION_MODEL)
    if torch.cuda.is_available():
        _model = _model.to("cuda")
    _model.eval()
except Exception:  # transformers / model weights not available in this env
    pass

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
    """Run the generation model.

    Raises
    ------
    RuntimeError
        When the HF generation model is unavailable (missing deps, failed load).
        Callers must catch this and return a structured error response.
    """
    if _model is None or _tokenizer is None:
        raise RuntimeError("generation_model_unavailable")
    device = next(_model.parameters()).device
    inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
    inputs = {k: v.to(device) for k, v in inputs.items()}

    output = _model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=_tokenizer.pad_token_id or _tokenizer.eos_token_id,
    )

    if _is_encoder_decoder:
        return _tokenizer.decode(output[0], skip_special_tokens=True)

    return _tokenizer.decode(
        output[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )


def generate_response_streaming(prompt: str, max_new_tokens: int = 200):
    """
    Stream tokens from LLM generation in real-time using TextIteratorStreamer.
    Yields Server-Sent Events (SSE) format: "data: {token_json}\\n\\n"

    This enables ChatGPT-like typing effect on the frontend with real-time feedback.
    Issue #118: Real-Time LLM Token Streaming
    """
    if _model is None or _tokenizer is None:
        yield f"data: {json.dumps({'error': 'generation_model_unavailable'})}\n\n"
        return

    device = next(_model.parameters()).device
    inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
    inputs = {k: v.to(device) for k, v in inputs.items()}

    streamer = TextIteratorStreamer(_tokenizer, skip_prompt=True, skip_special_tokens=True)

    generation_kwargs = {
        **inputs,
        "max_new_tokens": max_new_tokens,
        "do_sample": False,
        "pad_token_id": _tokenizer.pad_token_id or _tokenizer.eos_token_id,
        "streamer": streamer,
    }

    thread = threading.Thread(target=_model.generate, kwargs=generation_kwargs)
    thread.start()

    collected_tokens = []
    try:
        for token in streamer:
            collected_tokens.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"
    finally:
        thread.join()

    yield f"data: {json.dumps({'done': True})}\n\n"


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
    # SECURITY: Use only uuid4().hex to prevent path traversal from client filename
    file_path = os.path.join(upload_dir, f"{uuid4().hex}.pdf")
    upload_dir_resolved = os.path.abspath(upload_dir)
    file_path_resolved = os.path.abspath(file_path)
    
    # SECURITY: Validate that file_path is within upload_dir (prevent path traversal)
    if not file_path_resolved.startswith(upload_dir_resolved + os.sep):
        return {"error": "Upload failed: Invalid file path detected."}

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

        # Strict per-session isolation: each upload owns its own vectorstore.
        # Write is protected by the lock so concurrent uploads never race.
        with _session_lock:
            sessions[session_id] = {
                "vectorstores": [vectorstore],
                "filename": file.filename,
                "last_accessed": time.time(),
            }

        return {
            "message": "PDF uploaded and processed",
            "session_id": session_id,
            "page_count": len(docs),
        }

    except Exception as e:
        return {"error": f"Upload failed: {str(e)}"}
    
    finally:
        # FIX: Delete PDF file after processing to prevent disk space exhaustion (Issue #110)
        # This ensures the physical file is deleted even if OCR or embedding fails
        try:
            os.remove(file_path)
        except FileNotFoundError:
            # File already deleted or never created; nothing to clean up
            pass
        except OSError as delete_err:
            # Log other errors but don't crash
            print(f"[/upload] Warning: Failed to delete file: {str(delete_err)}")



# ===============================
# ASK (USES session_ids — matches fixed App.js)
# ===============================
@app.post("/ask")
@limiter.limit("60/15 minutes")
def ask_question(request: Request, data: AskRequest):
    cleanup_expired_sessions()

    if not data.session_ids:
        return {"answer": "No session selected.", "citations": []}

    # Snapshot relevant sessions under the lock, then do I/O outside it.
    with _session_lock:
        for sid in data.session_ids:
            s = sessions.get(sid)
            if s:
                s["last_accessed"] = time.time()
        _snap = {
            sid: sessions[sid]
            for sid in data.session_ids
            if sid in sessions
        }

    # Gather retrieved docs with their session filenames
    docs_with_meta = []
    for sid, session in _snap.items():
        vs = session["vectorstores"][0]
        filename = session.get("filename", "unknown")
        retrieved = vs.similarity_search(data.question, k=4)
        for doc in retrieved:
            docs_with_meta.append({
                "doc": doc,
                "filename": filename,
                "sid": sid
            })

    if not docs_with_meta:
        return {"answer": "No relevant context found.", "citations": []}

    # Build context with page annotations for the prompt
    context_parts = []
    for item in docs_with_meta:
        # PyPDFLoader sets metadata["page"] as 0-indexed
        raw_page = item["doc"].metadata.get("page", 0)
        page_num = int(raw_page) + 1  # Convert to 1-indexed
        context_parts.append(f"[Page {page_num}] {item['doc'].page_content}")

    context = "\n\n".join(context_parts)

    # Use minimal prompt builder to reduce instruction echoing (upstream fix)
    prompt = build_ask_prompt(context=context, question=data.question)
    try:
        raw_answer = generate_response(prompt, max_new_tokens=150)
    except RuntimeError:
        return {"answer": None, "error": "generation_model_unavailable"}
    # Strip any leaked prompt/context text from the raw output
    clean_answer = extract_final_answer(raw_answer)

    # Build deduplicated, sorted citations
    seen = set()
    citations = []
    for item in docs_with_meta:
        raw_page = item["doc"].metadata.get("page", 0)
        page_num = int(raw_page) + 1
        key = (item["filename"], page_num)
        if key not in seen:
            seen.add(key)
            citations.append({
                "page": page_num,
                "source": item["filename"],
            })

    citations.sort(key=lambda c: (c["source"], c["page"]))

    return {"answer": clean_answer, "citations": citations}


# ===============================
# ASK STREAM (REAL-TIME TOKEN STREAMING - Issue #118)
# ===============================
@app.post("/ask-stream")
@limiter.limit("60/15 minutes")
def ask_question_stream(request: Request, data: AskRequest):
    """
    Stream token-by-token generation using Server-Sent Events (SSE).

    Provides real-time typing effect similar to ChatGPT.
    Issue #118: Real-Time LLM Token Streaming

    Response format:
    - Each line: "data: {\"token\": \"word \"}\\n\\n"
    - End marker: "data: {\"done\": true}\\n\\n"
    """
    def generate():
        cleanup_expired_sessions()

        if not data.session_ids:
            yield f"data: {json.dumps({'error': 'No session selected.'})}\n\n"
            return

        with _session_lock:
            for sid in data.session_ids:
                s = sessions.get(sid)
                if s:
                    s["last_accessed"] = time.time()
            _snap = {
                sid: sessions[sid]
                for sid in data.session_ids
                if sid in sessions
            }

        docs_with_meta = []
        for sid, session in _snap.items():
            vs = session["vectorstores"][0]
            filename = session.get("filename", "unknown")
            retrieved = vs.similarity_search(data.question, k=4)
            for doc in retrieved:
                docs_with_meta.append({
                    "doc": doc,
                    "filename": filename,
                    "sid": sid
                })

        if not docs_with_meta:
            yield f"data: {json.dumps({'error': 'No relevant context found.'})}\n\n"
            return

        context_parts = []
        for item in docs_with_meta:
            raw_page = item["doc"].metadata.get("page", 0)
            page_num = int(raw_page) + 1
            context_parts.append(f"[Page {page_num}] {item['doc'].page_content}")

        context = "\n\n".join(context_parts)
        prompt = build_ask_prompt(context=context, question=data.question)

        seen = set()
        citations = []
        for item in docs_with_meta:
            raw_page = item["doc"].metadata.get("page", 0)
            page_num = int(raw_page) + 1
            key = (item["filename"], page_num)
            if key not in seen:
                seen.add(key)
                citations.append({"page": page_num, "source": item["filename"]})

        citations.sort(key=lambda c: (c["source"], c["page"]))
        yield f"data: {json.dumps({'citations': citations, 'type': 'metadata'})}\n\n"

        # Stream tokens from LLM generation while accumulating them for post-processing
        accumulated_tokens = []
        for token_chunk in generate_response_streaming(prompt, max_new_tokens=150):
            # Pass through the streamed chunk as-is for real-time display
            yield token_chunk
            
            # Attempt to parse "data: {...}" SSE chunks to extract tokens
            try:
                chunk_str = token_chunk.strip()
                if chunk_str.startswith("data: "):
                    payload_str = chunk_str[len("data: "):].strip()
                    if payload_str:
                        payload = json.loads(payload_str)
                        if isinstance(payload, dict) and "token" in payload:
                            token_text = payload.get("token")
                            if isinstance(token_text, str):
                                accumulated_tokens.append(token_text)
            except Exception:
                # If parsing fails, skip accumulation but continue streaming
                pass
        
        # After streaming completes, post-process the full answer to strip any
        # prompt/context leakage and emit a final sanitized answer event.
        if accumulated_tokens:
            raw_answer = "".join(accumulated_tokens)
            try:
                cleaned_answer = extract_final_answer(raw_answer)
            except Exception:
                # If extraction fails, use raw answer
                cleaned_answer = raw_answer
            
            final_event = {
                "type": "final_answer",
                "answer": cleaned_answer,
            }
            yield f"data: {json.dumps(final_event)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ===============================
# SUMMARIZE
# ===============================
@app.post("/summarize")
@limiter.limit("15/15 minutes")
def summarize_pdf(request: Request, data: SummarizeRequest):
    cleanup_expired_sessions()

    if not data.session_ids:
        return {"summary": "No session selected."}

    with _session_lock:
        _snap = {
            sid: sessions[sid]
            for sid in data.session_ids
            if sid in sessions
        }

    vectorstores = []
    for session in _snap.values():
        vectorstores.extend(session["vectorstores"])

    if not vectorstores:
        return {"summary": "No documents found."}

    docs = []
    for vs in vectorstores:
        docs.extend(vs.similarity_search("Summarize the document", k=6))

    context = "\n\n".join([d.page_content for d in docs])

    # ── Build minimal summarization prompt ───────────────────────────────────
    prompt = build_summarize_prompt(context=context)

    try:
        raw_summary = generate_response(prompt, max_new_tokens=300)
    except RuntimeError:
        return {"summary": None, "error": "generation_model_unavailable"}
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

    with _session_lock:
        _snap = {
            sid: sessions[sid]
            for sid in data.session_ids
            if sid in sessions
        }

    contexts = []
    for session in _snap.values():
        vs = session["vectorstores"][0]
        chunks = vs.similarity_search("main topics", k=4)
        text = "\n".join([c.page_content for c in chunks])
        contexts.append(text)

    # Retrieve top chunks from each document separately for fair comparison
    query = "summarize the main topic, purpose, and key details of this document"
    per_doc_contexts = []
    for session in _snap.values():
        vs = session["vectorstores"][0]
        chunks = vs.similarity_search(query, k=4)
        text = "\n".join([c.page_content for c in chunks])
        per_doc_contexts.append(text)

    # ── Build minimal comparison prompt ───────────────────────────────────────
    prompt = build_compare_prompt(per_doc_contexts=per_doc_contexts)

    try:
        raw = generate_response(prompt, max_new_tokens=400)
    except RuntimeError:
        return {"comparison": None, "error": "generation_model_unavailable"}
    # Post-process: strip any leaked prompt/context text from the comparison.
    comparison = extract_comparison(raw)
    return {"comparison": comparison}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000)