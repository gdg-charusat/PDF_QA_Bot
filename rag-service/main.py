from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, validator
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document
from dotenv import load_dotenv
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
from slowapi import Limiter
from slowapi.util import get_remote_address

# -------------------------------------------------------------------
# APP SETUP
# -------------------------------------------------------------------
load_dotenv()
app = FastAPI()

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-base")
LLM_GENERATION_TIMEOUT = int(os.getenv("LLM_GENERATION_TIMEOUT", "30"))

SESSION_TIMEOUT = 3600  # 1 hour
sessions = {}  # { session_id: { vectorstore, last_accessed } }

# -------------------------------------------------------------------
# MODELS
# -------------------------------------------------------------------
generation_tokenizer = None
generation_model = None
generation_is_encoder_decoder = False

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
    text = re.sub(
        r"^(Answer[^:]*:|Context:|Question:)\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
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

    encoded = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=2048,
    )
    encoded = {k: v.to(device) for k, v in encoded.items()}

    pad_token_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    try:
        output_ids = generate_with_timeout(
            model,
            encoded,
            max_new_tokens,
            pad_token_id,
            LLM_GENERATION_TIMEOUT,
        )
    except TimeoutException:
        raise HTTPException(status_code=504, detail="Model timed out")

    if is_encoder_decoder:
        return tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()

    input_len = encoded["input_ids"].shape[1]
    return tokenizer.decode(
        output_ids[0][input_len:], skip_special_tokens=True
    ).strip()

# -------------------------------------------------------------------
# REQUEST MODELS
# -------------------------------------------------------------------
class PDFPath(BaseModel):
    filePath: str
    session_id: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str
    history: list = []

    @validator("question")
    def validate_question(cls, v):
        if not v.strip():
            raise ValueError("Question cannot be empty")
        return v.strip()


class SummarizeRequest(BaseModel):
    session_id: str

# -------------------------------------------------------------------
# SESSION CLEANUP
# -------------------------------------------------------------------
def cleanup_expired_sessions():
    now = time.time()
    expired = [
        sid for sid, s in sessions.items()
        if now - s["last_accessed"] > SESSION_TIMEOUT
    ]
    for sid in expired:
        del sessions[sid]

# -------------------------------------------------------------------
# ENDPOINTS
# -------------------------------------------------------------------
@app.post("/process-pdf")
@limiter.limit("15/15 minutes")
def process_pdf(request: Request, data: PDFPath):
    cleanup_expired_sessions()

    if not os.path.exists(data.filePath):
        raise HTTPException(status_code=404, detail="PDF not found")

    # Check file size
    file_size = os.path.getsize(data.filePath)
    if file_size == 0:
        return {"error": "PDF file is empty."}
    
    if file_size > 10 * 1024 * 1024:  # 10MB limit
        return {"error": "PDF file exceeds 10MB size limit."}

    try:
        loader = PyPDFLoader(data.filePath)
        docs = loader.load()
    except Exception as e:
        return {"error": f"Failed to read PDF. The file may be corrupted or password-protected: {str(e)}"}

    # Validate PDF has content
    if not docs:
        return {"error": "PDF has no pages or is corrupted."}
    
    # Check if PDF has readable text
    total_text = "".join([doc.page_content for doc in docs]).strip()
    if not total_text or len(total_text) < 10:
        return {"error": "PDF has no readable text content. It may be image-based or corrupted."}
    loader = PyPDFLoader(data.filePath)
    raw_docs = loader.load()

    cleaned_docs = [
        Document(
            page_content=normalize_spaced_text(doc.page_content),
            metadata=doc.metadata,
        )
        for doc in raw_docs
    ]

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = splitter.split_documents(cleaned_docs)

    if not chunks:
        raise HTTPException(status_code=400, detail="No text extracted from PDF")

    sessions[data.session_id] = {
        "vectorstore": FAISS.from_documents(chunks, embedding_model),
        "last_accessed": time.time(),
    }

    return {"message": "PDF processed successfully"}


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
        f"Context:\n{context}\n\n"
        f"Question: {data.question}\nAnswer:"
    )

    answer = generate_response(prompt, max_new_tokens=256)
    return {"answer": normalize_answer(answer)}


@app.post("/summarize")
@limiter.limit("15/15 minutes")
def summarize_pdf(request: Request, data: SummarizeRequest):
    cleanup_expired_sessions()

    session = sessions.get(data.session_id)
    if not session:
        return {"summary": "Session expired or PDF not uploaded"}

    session["last_accessed"] = time.time()
    vectorstore = session["vectorstore"]

    docs = vectorstore.similarity_search("Summarize the document.", k=6)
    if not docs:
        return {"summary": "No content available"}

    context = "\n\n".join(doc.page_content for doc in docs)

    prompt = (
        "Summarize the document in 6-8 concise bullet points.\n"
        f"Context:\n{context}\nSummary:"
    )

    summary = generate_response(prompt, max_new_tokens=220)
    return {"summary": normalize_answer(summary)}

# -------------------------------------------------------------------
# START SERVER
# -------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)