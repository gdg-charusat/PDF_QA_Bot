from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, validator
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from groq import Groq
from dotenv import load_dotenv
from transformers import (
    AutoConfig,
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    AutoModelForCausalLM,
)
from slowapi import Limiter
from slowapi.util import get_remote_address
from pathlib import Path
import os 
import re
import uvicorn
import torch
import time
import docx
from slowapi import Limiter
from slowapi.util import get_remote_address
import threading
from datetime import datetime

# ===============================
# APP SETUP
# ===============================
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = (BASE_DIR / "uploads").resolve()

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# ===============================
# CONFIG
# ===============================
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-small")
LLM_GENERATION_TIMEOUT = int(os.getenv("LLM_GENERATION_TIMEOUT", "30"))
SESSION_TIMEOUT = 3600

# ===============================
# QUERY CONDENSATION PROMPT
# ===============================
CONDENSE_QUESTION_PROMPT = """Given the following conversation history and a follow-up question, 
rewrite the follow-up question to be a standalone, self-contained question that can be understood 
without the conversation history. Replace pronouns (it, they, this, that, he, she) with the actual 
entities they refer to from the conversation history.

Conversation History:
{history}

Follow-up Question: {question}

Standalone Question:"""

# ---------------------------------------------------------------------------
# GLOBAL STATE MANAGEMENT (Thread-safe, Multi-user support)
# ---------------------------------------------------------------------------
# Per-user/session storage with proper cleanup and locking
sessions = {}  # {session_id: {"vectorstore": FAISS, "upload_time": datetime}}
sessions_lock = threading.RLock()  # Thread-safe access to sessions

# Generation model globals (lazy-loaded)
generation_model = None
generation_tokenizer = None
generation_is_encoder_decoder = None

# Load local embedding model (unchanged — FAISS retrieval stays the same)
embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# ---------------------------------------------------------------------------
# SESSION MANAGEMENT UTILITIES (Thread-safe, Multi-user support)
# ---------------------------------------------------------------------------

def get_session_vectorstore(session_id: str):
    """
    Safely retrieves vectorstore for a session.
    Returns (vectorstore, upload_time) or (None, None) if not found.
    """
    with sessions_lock:
        if session_id in sessions:
            session_data = sessions[session_id]
            return session_data.get("vectorstore"), session_data.get("upload_time")
        return None, None


def set_session_vectorstore(session_id: str, vectorstore, upload_time: str):
    """
    Safely stores vectorstore for a session.
    Clears old session if it exists (replaces it).
    """
    with sessions_lock:
        # Clear old session to prevent memory leaks
        if session_id in sessions:
            old_vectorstore = sessions[session_id].get("vectorstore")
            if old_vectorstore is not None:
                del old_vectorstore  # Allow garbage collection
        
        # Store new session
        sessions[session_id] = {
            "vectorstore": vectorstore,
            "upload_time": upload_time
        }


def clear_session(session_id: str):
    """
    Safely clears a specific session's vectorstore and data.
    """
    with sessions_lock:
        if session_id in sessions:
            old_vectorstore = sessions[session_id].get("vectorstore")
            if old_vectorstore is not None:
                del old_vectorstore  # Allow garbage collection
            del sessions[session_id]


def normalize_spaced_text(text: str) -> str:
    pattern = r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b"
    return re.sub(pattern, lambda m: m.group(0).replace(" ", ""), text)


def normalize_answer(text: str) -> str:
    """
    Post-processes the LLM-generated answer.
    """
    text = normalize_spaced_text(text)
    text = re.sub(r"^(Answer[^:]*:|Context:|Question:)\s*", "", text, flags=re.I)
    return text.strip()


def condense_question(question: str, history: list) -> str:
    """
    Condense a follow-up question using conversation history into a standalone query.
    This handles pronouns and context-dependent references.
    """
    if not history or len(history) < 1:
        return question
    
    # Build history context from last 3-5 messages
    history_text = ""
    for msg in history[-5:]:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role and content:
            history_text += f"{role}: {content}\n"
    
    if not history_text.strip():
        return question
    
    # Use LLM to rewrite the question
    prompt = CONDENSE_QUESTION_PROMPT.format(
        history=history_text.strip(),
        question=question
    )
    
    try:
        condensed = generate_response(prompt, max_new_tokens=128)
        condensed = condensed.strip()
        
        # Return condensed question if valid, otherwise original
        if condensed and len(condensed) > 3:
            return condensed
    except Exception:
        pass
    
    return question


# ===============================
# DOCUMENT LOADERS
# ===============================
def load_pdf(file_path: str):
    return PyPDFLoader(file_path).load()


def load_txt(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        return [Document(page_content=f.read())]


def load_docx(file_path: str):
    doc = docx.Document(file_path)
    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    return [Document(page_content=text)]


def load_document(file_path: str):
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return load_pdf(file_path)
    elif ext == ".docx":
        return load_docx(file_path)
    elif ext in [".txt", ".md"]:
        return load_txt(file_path)
    else:
        raise ValueError("Unsupported file format")


# ===============================
# MODEL LOADING
# ===============================
def load_generation_model():
    global generation_model, generation_tokenizer, generation_is_encoder_decoder

    if generation_model:
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


def generate_response(prompt: str, max_new_tokens: int):
    tokenizer, model, is_enc = load_generation_model()
    device = next(model.parameters()).device

    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
    encoded = {k: v.to(device) for k, v in encoded.items()}

    output = model.generate(
        **encoded,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
    )

    if is_enc:
        return tokenizer.decode(output[0], skip_special_tokens=True)

    return tokenizer.decode(
        output[0][encoded["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )


# ===============================
# REQUEST MODELS
# ===============================
class DocumentPath(BaseModel):
    filePath: str
    session_id: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str
    history: list = []

    @validator("question")
    def validate_question(cls, v):
        if not v.strip():
            raise ValueError("Empty question")
        return v.strip()


class SummarizeRequest(BaseModel):
    session_id: str
    pdf: str | None = None



class CompareRequest(BaseModel):
    session_id: str

# -------------------------------------------------------------------
# SESSION CLEANUP
# -------------------------------------------------------------------


def cleanup_expired_sessions():
    now = time.time()
    expired = [k for k, v in sessions.items()
               if now - v["last"] > SESSION_TIMEOUT]
    for k in expired:
        del sessions[k]


# ===============================
# PROCESS DOCUMENT
# ===============================
@app.post("/process")
@limiter.limit("15/15 minutes")
def process_pdf(request: Request, data: PDFPath):
    """
    Process and store PDF with proper cleanup and thread-safe multi-user support.
    """
    try:
        loader = PyPDFLoader(data.filePath)
        raw_docs = loader.load()

        if not raw_docs:
            return {"error": "PDF file is empty or unreadable. Please check your file."}

        # ── Layer 1: normalize at ingestion ──────────────────────────────────────
        cleaned_docs = []
        for doc in raw_docs:
            cleaned_content = normalize_spaced_text(doc.page_content)
            cleaned_docs.append(Document(page_content=cleaned_content, metadata=doc.metadata))

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        chunks = splitter.split_documents(cleaned_docs)
        
        if not chunks:
            return {"error": "No text chunks generated from the PDF. Please check your file."}

        # **KEY FIX**: Store per-session with automatic cleanup of old data
        session_id = request.headers.get("X-Session-ID", "default")
        upload_time = datetime.now().isoformat()
        
        # Thread-safe storage (automatically clears old session data)
        vectorstore = FAISS.from_documents(chunks, embedding_model)
        set_session_vectorstore(session_id, vectorstore, upload_time)
        
        return {
            "message": "PDF processed successfully",
            "session_id": session_id,
            "upload_time": upload_time,
            "chunks_created": len(chunks)
        }
            
    except Exception as e:
        return {
            "error": f"PDF processing failed: {str(e)}",
            "details": "Please ensure the file is a valid PDF"
        }


@app.post("/ask")
@limiter.limit("60/15 minutes")
def ask_question(request: Request, data: AskRequest):
    """
    Answer questions using session-specific PDF context with thread-safe access.
    """
    session_id = request.headers.get("X-Session-ID", "default")
    vectorstore, upload_time = get_session_vectorstore(session_id)
    
    if vectorstore is None:
        return {"answer": "Please upload a PDF first!"}
    
    try:
        # Thread-safe vectorstore access
        with sessions_lock:
            question = data.question
            history = data.history
            conversation_context = ""
            
            if history:
                for msg in history[-5:]:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role and content:
                        conversation_context += f"{role}: {content}\n"
            
            # QUERY CONDENSATION: Rewrite question to standalone form using history
            standalone_query = condense_question(question, history)
            
            # Search only within current session's vectorstore using condensed query
            docs = vectorstore.similarity_search(standalone_query, k=4)
            if not docs:
                return {"answer": "No relevant context found in the current PDF."}

            context = "\n\n".join([doc.page_content for doc in docs])

            prompt = f"""You are a helpful assistant answering questions ONLY from the provided PDF document.

Conversation History (for context only):
{conversation_context}

Document Context (ONLY reference this):
{context}

Current Question:
{question}

Instructions:
- Answer ONLY using the document context provided above.
- Do NOT use any information from previous documents or conversations outside this context.
- If the answer is not in the document, say so briefly.
- Keep the answer concise (2-3 sentences max).

Answer:"""

            raw_answer = generate_response(prompt, max_new_tokens=512)
            answer = normalize_answer(raw_answer)
            return {"answer": answer}
            
    except Exception as e:
        return {"answer": f"Error processing question: {str(e)}"}

    return {"answer": normalize_answer(answer), "confidence_score": 85}

@app.post("/summarize")
@limiter.limit("15/15 minutes")
def summarize_pdf(request: Request, data: SummarizeRequest):
    """
    Summarize PDF using session-specific context with thread-safe access.
    """
    session_id = request.headers.get("X-Session-ID", "default")
    vectorstore, upload_time = get_session_vectorstore(session_id)
    
    if vectorstore is None:
        return {"summary": "Please upload a PDF first!"}

    try:
        # Thread-safe vectorstore access
        with sessions_lock:
            docs = vectorstore.similarity_search("Give a concise summary of the document.", k=6)
            if not docs:
                return {"summary": "No document context available to summarize."}

            context = "\n\n".join([doc.page_content for doc in docs])

            prompt = (
                "You are a document summarization assistant working with a certificate or official document.\n"
                "RULES:\n"
                "1. Summarize in 6-8 concise bullet points.\n"
                "2. Clearly distinguish: who received the certificate, what course, which company issued it,\n"
                "   who signed it, on what platform, and on what date.\n"
                "3. Return clean, properly formatted text — no character spacing, proper Title Case for names.\n"
                "4. Use ONLY the information in the context below.\n"
                "5. DO NOT reference any other documents or previous PDFs.\n\n"
                f"Context:\n{context}\n\n"
                "Summary (bullet points):"
            )

            raw_summary = generate_response(prompt, max_new_tokens=512)
            summary = normalize_answer(raw_summary)
            return {"summary": summary}
            
    except Exception as e:
        return {"summary": f"Error summarizing PDF: {str(e)}"}


@app.post("/compare")
@limiter.limit("15/15 minutes")
def compare_pdfs(request: Request, data: dict):
    """
    Compare two PDFs using their session-specific contexts.
    Supports multi-user/multi-PDF comparison feature.
    """
    session_id_1 = data.get("session_id_1", "default")
    session_id_2 = data.get("session_id_2", "default")
    question = data.get("question", "Compare these documents")
    
    vectorstore_1, _ = get_session_vectorstore(session_id_1)
    vectorstore_2, _ = get_session_vectorstore(session_id_2)
    
    if vectorstore_1 is None or vectorstore_2 is None:
        return {"error": "One or both sessions do not have a PDF loaded"}
    
    try:
        with sessions_lock:
            docs_1 = vectorstore_1.similarity_search(question, k=3)
            docs_2 = vectorstore_2.similarity_search(question, k=3)
            
            context_1 = "\n\n".join([doc.page_content for doc in docs_1])
            context_2 = "\n\n".join([doc.page_content for doc in docs_2])
            
            prompt = f"""You are a document comparison assistant.

PDF 1 Context:
{context_1}

PDF 2 Context:
{context_2}

Question: {question}

Compare the two documents regarding this question and highlight key differences and similarities.

Comparison:"""
            
            comparison = generate_response(prompt, max_new_tokens=512)
            return {"comparison": normalize_answer(comparison)}
            
    except Exception as e:
        return {"error": f"Error comparing PDFs: {str(e)}"}


@app.post("/reset")
@limiter.limit("60/15 minutes")
def reset_session(request: Request):
    """
    Explicitly resets a session by clearing its vectorstore.
    """
    session_id = request.headers.get("X-Session-ID", "default")
    
    with sessions_lock:
        clear_session(session_id)
        
    return {
        "message": "Session cleared successfully",
        "session_id": session_id
    }


@app.get("/status")
def get_pdf_status(request: Request):
    """
    Returns the current PDF session status.
    Useful for debugging and ensuring proper state management.
    """
    session_id = request.headers.get("X-Session-ID", "default")
    
    with sessions_lock:
        if session_id in sessions:
            return {
                "pdf_loaded": True,
                "session_id": session_id,
                "upload_time": sessions[session_id].get("upload_time")
            }
        return {
            "pdf_loaded": False,
            "session_id": session_id,
            "upload_time": None
        }


# -------------------------------------------------------------------
# START SERVER
# -------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)