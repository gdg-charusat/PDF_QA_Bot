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
from pathlib import Path
import docx

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
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-small")
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


SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"]


# ===============================
# DOCUMENT LOADERS
# ===============================
def load_pdf(file_path: str) -> list[Document]:
    """Load a PDF file using PyPDFLoader."""
    loader = PyPDFLoader(file_path)
    return loader.load()


def _extract_full_text_from_docx(doc) -> str:
    """Extract text from paragraphs, tables, headers, and footers in a DOCX file."""
    texts: list[str] = []

    def add_paragraphs(paragraphs):
        for para in paragraphs:
            text = para.text.strip()
            if text:
                texts.append(text)

    def add_table(table):
        for row in table.rows:
            for cell in row.cells:
                add_paragraphs(cell.paragraphs)
                for inner_table in cell.tables:
                    add_table(inner_table)

    # Body paragraphs and tables
    add_paragraphs(doc.paragraphs)
    for table in doc.tables:
        add_table(table)

    # Headers and footers
    for section in doc.sections:
        header = section.header
        footer = section.footer
        if header is not None:
            add_paragraphs(header.paragraphs)
            for table in header.tables:
                add_table(table)
        if footer is not None:
            add_paragraphs(footer.paragraphs)
            for table in footer.tables:
                add_table(table)

    return "\n".join(texts)


def load_docx(file_path: str) -> list[Document]:
    """Load a DOCX file using python-docx (extracts paragraphs, tables, headers, footers)."""
    doc = docx.Document(file_path)
    full_text = _extract_full_text_from_docx(doc)
    if not full_text.strip():
        return []
    return [Document(page_content=full_text, metadata={"source": file_path})]


def load_txt(file_path: str) -> list[Document]:
    """Load a plain text file."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return []
    return [Document(page_content=content, metadata={"source": file_path})]


def load_md(file_path: str) -> list[Document]:
    """Load a Markdown file (treated as plain text for RAG)."""
    return load_txt(file_path)


def load_document(file_path: str) -> list[Document]:
    """Route to the appropriate loader based on file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return load_pdf(file_path)
    elif ext == ".docx":
        return load_docx(file_path)
    elif ext in (".txt", ".md"):
        return load_txt(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext}. Supported: {SUPPORTED_EXTENSIONS}")


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

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
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

class DocumentPath(BaseModel):
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
def process_pdf(request: Request, data: DocumentPath):
    cleanup_expired_sessions()
    
    if not os.path.exists(data.filePath):
        raise HTTPException(status_code=404, detail="Document not found")

    ext = Path(data.filePath).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {ext}. Supported: {', '.join(SUPPORTED_EXTENSIONS)}")

    try:
        raw_docs = load_document(data.filePath)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load document: {str(e)}")

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
        raise HTTPException(status_code=400, detail="No text extracted from the document. Please check your file.")

    sessions[data.session_id] = {
        "vectorstore": FAISS.from_documents(chunks, embedding_model),
        "last_accessed": time.time(),
    }

    return {"message": "PDF processed successfully"}


# ===============================
# RELEVANCE CONFIGURATION
# ===============================
# Uses cosine similarity (0 to 1) instead of raw L2 distance.
# 0.0 = completely unrelated, 1.0 = identical match.
# NOTE: The conversion from FAISS scores to cosine similarity assumes that
# embeddings are L2-normalized and that FAISS uses IndexFlatL2 (L2 squared).
RELEVANCE_THRESHOLD = 0.25  # Minimum cosine similarity for relevance


def faiss_score_to_cosine_sim(score: float) -> float:
    """Convert a FAISS L2 squared distance score to cosine similarity.

    Assumptions:
    - Embedding vectors are L2-normalized (||v|| = 1). True for many
      sentence-transformer models including all-MiniLM-L6-v2.
    - The FAISS index returns L2 squared distances (e.g., IndexFlatL2).

    Under these conditions:
        ||u - v||^2 = 2 - 2 * cos(theta)
        => cos(theta) = 1 - (||u - v||^2 / 2)

    The returned value is clamped to [0.0, 1.0] for numerical stability.
    """
    return max(0.0, 1.0 - score / 2.0)


def compute_confidence(faiss_scores: list[float]) -> float:
    """Compute confidence (0-100%) from FAISS scores using the top-3 chunks.

    The provided FAISS scores are assumed to be L2 squared distances for
    L2-normalized embeddings (see ``faiss_score_to_cosine_sim``). Scores are
    converted to cosine similarities and the top-3 most relevant chunks are
    averaged to produce a confidence value in percent.
    """
    if not faiss_scores:
        return 0.0
    top_scores = sorted(faiss_scores)[:3]
    similarities = [faiss_score_to_cosine_sim(s) for s in top_scores]
    avg_sim = sum(similarities) / len(similarities)
    return round(float(avg_sim * 100), 1)


@app.post("/ask")
@limiter.limit("60/15 minutes")
def ask_question(request: Request, data: AskRequest):
    cleanup_expired_sessions()

    session_data = sessions.get(data.session_id)
    if not session_data:
        return {"answer": "Session expired or no PDF uploaded for this session!", "confidence_score": 0}

    session_data["last_accessed"] = time.time()
    vectorstore = session_data["vectorstore"]

    question = data.question
    history = data.history
    conversation_context = ""
    # Use only last 5 messages to avoid long prompts
    for msg in history[-5:]:
        role = msg.get("role", "")
        content = msg.get("content", "")
        conversation_context += f"{role}: {content}\n"

    # Use similarity_search_with_score to get FAISS L2 squared distances
    docs_with_scores = vectorstore.similarity_search_with_score(question, k=4)
    if not docs_with_scores:
        return {"answer": "No relevant context found.", "confidence_score": 0}

    # Convert FAISS scores to cosine similarities once (avoid redundant computation)
    scored = [(doc, score, faiss_score_to_cosine_sim(score)) for doc, score in docs_with_scores]
    similarities = [sim for _, _, sim in scored]
    top3_sims = sorted(similarities, reverse=True)[:3]
    top3_avg_sim = sum(top3_sims) / len(top3_sims)
    confidence = round(float(top3_avg_sim * 100), 1)

    # Reject if top-3 average cosine similarity is below threshold
    if top3_avg_sim < RELEVANCE_THRESHOLD:
        return {
            "answer": "I cannot answer this question based on the uploaded document. "
                      "The question appears to be unrelated to the document content.",
            "confidence_score": confidence
        }

    # Filter to only keep chunks above relevance threshold
    relevant_docs = [doc for doc, _, sim in scored if sim >= RELEVANCE_THRESHOLD]
    # At least one doc must pass since top3_avg_sim >= RELEVANCE_THRESHOLD
    assert relevant_docs, "Invariant violated: relevant_docs should not be empty"

    # Context is already clean (normalized at ingestion)
    context = "\n\n".join([d.page_content for d in relevant_docs])

    prompt = f"""
    You are a helpful assistant answering ONLY from the document context below.

    Conversation History:
    {conversation_context}

    Document Context:
    {context}

    Current Question:
    {question}

    Instructions:
    - Use the document context to answer.
    - If the answer is not in the document, say so briefly.
    - Keep the answer concise.

    Answer:
    """

    raw_answer = generate_response(prompt, max_new_tokens=128)

    # ── Layer 3: post-process the answer itself ───────────────────────────────
    answer = normalize_answer(raw_answer)
    return {"answer": answer, "confidence_score": confidence}


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