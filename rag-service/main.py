from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, validator
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from dotenv import load_dotenv
import os
import uvicorn
import torch
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoConfig, AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM
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
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError

# -------------------------------------------------------------------
# APP SETUP
# -------------------------------------------------------------------
load_dotenv()
app = FastAPI()

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# ===============================
# GLOBAL STATE
# ===============================
vectorstore = None
qa_chain = False
VECTOR_STORE = None
DOCUMENT_REGISTRY = {}
DOCUMENT_EMBEDDINGS = {}
CHAT_HISTORY = []  # Session-based chat history
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

# ===============================
# EMBEDDING MODEL
# ===============================
embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# ===============================
# MODEL LOADING
# ===============================
def load_generation_model():
    global generation_tokenizer, generation_model, generation_is_encoder_decoder

    if generation_model is not None:
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

    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
    encoded = {k: v.to(device) for k, v in encoded.items()}
    pad_token_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    with torch.no_grad():
        output_ids = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=pad_token_id,
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
    new_tokens = output_ids[0][input_len:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


# ===============================
# REQUEST MODELS
# ===============================
    return tokenizer.decode(
        output_ids[0][input_len:], skip_special_tokens=True
    ).strip()

# -------------------------------------------------------------------
# REQUEST MODELS
# -------------------------------------------------------------------
class PDFPath(BaseModel):
    filePath: str


class Question(BaseModel):
    question: str
    doc_ids: list[str] | None = None
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
    doc_ids: list[str] | None = None


class CompareRequest(BaseModel):
    doc_ids: list[str]


# ===============================
# PROCESS PDF (MULTI-DOC SUPPORT)
# ===============================
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
def process_pdf(data: PDFPath):
    global vectorstore, qa_chain, VECTOR_STORE, DOCUMENT_REGISTRY, DOCUMENT_EMBEDDINGS, CHAT_HISTORY

    # Validate file exists
    if not os.path.exists(data.filePath):
        raise HTTPException(status_code=400, detail="File not found.")
    
    # Validate file size
    file_size = os.path.getsize(data.filePath)
    if file_size == 0:
        raise HTTPException(status_code=400, detail="PDF file is empty.")
    
    # Validate PDF structure and readability
    try:
        pdf_reader = PdfReader(data.filePath)
        if len(pdf_reader.pages) == 0:
            raise HTTPException(status_code=400, detail="PDF has no pages.")
        
        # Check if PDF has readable text
        has_text = False
        for page in pdf_reader.pages[:3]:  # Check first 3 pages
            if page.extract_text().strip():
                has_text = True
                break
        
        if not has_text:
            raise HTTPException(status_code=400, detail="PDF has no readable text content. It may be scanned or image-based.")
    
    except PdfReadError:
        raise HTTPException(status_code=400, detail="PDF file is corrupted or invalid.")
    except Exception as e:
        if "corrupted" in str(e).lower() or "invalid" in str(e).lower():
            raise HTTPException(status_code=400, detail="PDF file is corrupted or invalid.")
        raise HTTPException(status_code=500, detail=f"Error validating PDF: {str(e)}")

    # Process PDF
    try:
        loader = PyPDFLoader(data.filePath)
        docs = loader.load()
        
        if not docs:
            raise HTTPException(status_code=400, detail="Could not extract content from PDF.")

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        
        if not chunks:
            raise HTTPException(status_code=400, detail="No text content found in PDF.")
        
        # Generate doc_id from filename
        doc_id = os.path.basename(data.filePath)
        filename = os.path.basename(data.filePath)
        
        # Add doc_id to metadata
        for chunk in chunks:
            chunk.metadata["doc_id"] = doc_id
        
        # Update global vectorstore
        if VECTOR_STORE is None:
            VECTOR_STORE = FAISS.from_documents(chunks, embedding_model)
        else:
            VECTOR_STORE.add_documents(chunks)
        
        # Update legacy vectorstore for backward compatibility
        vectorstore = VECTOR_STORE
        qa_chain = True
        
        # Store document embeddings
        embeddings = embedding_model.embed_documents([c.page_content for c in chunks])
        doc_vector = np.mean(embeddings, axis=0)
        DOCUMENT_EMBEDDINGS[doc_id] = doc_vector
        
        # Register document
        DOCUMENT_REGISTRY[doc_id] = {
            "filename": filename,
            "num_chunks": len(chunks)
        }
        
        # Reset chat history for new document
        CHAT_HISTORY = []

        return {"message": "PDF processed successfully", "doc_id": doc_id}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")


# ===============================
# LIST DOCUMENTS
# ===============================
@app.get("/documents")
def list_documents():
    return DOCUMENT_REGISTRY


# ===============================
# SIMILARITY MATRIX
# ===============================
@app.get("/similarity-matrix")
def similarity_matrix():
    if len(DOCUMENT_EMBEDDINGS) < 2:
        return {"error": "At least 2 documents required."}

    doc_ids = list(DOCUMENT_EMBEDDINGS.keys())
    vectors = np.array([DOCUMENT_EMBEDDINGS[d] for d in doc_ids])
    sim_matrix = cosine_similarity(vectors)

    result = {}
    for i, doc_id in enumerate(doc_ids):
        result[doc_id] = {}
        for j, other_id in enumerate(doc_ids):
            result[doc_id][other_id] = float(sim_matrix[i][j])

    return result


# ===============================
# ASK QUESTION (WITH CHAT HISTORY)
# ===============================
@app.post("/ask")
@limiter.limit("60/15 minutes")
def ask_question(data: Question):
    global vectorstore, qa_chain, VECTOR_STORE, CHAT_HISTORY

    # Use VECTOR_STORE if available, fallback to vectorstore
    active_store = VECTOR_STORE or vectorstore
    
    if not qa_chain and active_store is None:
        return {"answer": "Please upload at least one PDF first!"}

    # Retrieve relevant documents
    docs = active_store.similarity_search(data.question, k=10)

    # Filter by doc_ids if provided
    if data.doc_ids:
        docs = [d for d in docs if d.metadata.get("doc_id") in data.doc_ids]

    if not docs:
        return {"answer": "No relevant context found."}
    if not os.path.exists(data.filePath):
        raise HTTPException(status_code=404, detail="PDF not found")

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

    context = "\n\n".join([d.page_content for d in docs])
    
    # Build chat history context
    history_context = ""
    if CHAT_HISTORY:
        history_context = "\n\nPrevious conversation:\n"
        for entry in CHAT_HISTORY[-3:]:  # Last 3 exchanges
            history_context += f"Q: {entry['question']}\nA: {entry['answer']}\n"

    # Build prompt with history
    if data.doc_ids and len(data.doc_ids) > 1:
        prompt = (
            "You are an AI assistant comparing multiple documents.\n"
            "Clearly structure your answer as:\n"
            "- Similarities\n"
            "- Differences\n"
            "- Unique points per document\n\n"
            f"{history_context}\n"
            f"Context:\n{context}\n\n"
            f"Question: {data.question}\n"
            "Answer:"
        )
    else:
        prompt = (
            "You are a helpful assistant answering questions about a PDF.\n"
            "Use ONLY the provided context.\n\n"
            f"{history_context}\n"
            f"Context:\n{context}\n\n"
            f"Question: {data.question}\n"
            "Answer:"
        )

    answer = generate_response(prompt, max_new_tokens=300)
    
    # Store in chat history
    CHAT_HISTORY.append({
        "question": data.question,
        "answer": answer
    })
    
    return {"answer": answer}


# ===============================
# SUMMARIZE
# ===============================
@app.post("/summarize")
@limiter.limit("15/15 minutes")
def summarize_pdf(data: SummarizeRequest):
    global vectorstore, qa_chain, VECTOR_STORE

    # Use VECTOR_STORE if available, fallback to vectorstore
    active_store = VECTOR_STORE or vectorstore
    
    if not qa_chain and active_store is None:
        return {"summary": "Please upload at least one PDF first!"}

    docs = active_store.similarity_search("Summarize the document.", k=12)

    if data.doc_ids:
        docs = [d for d in docs if d.metadata.get("doc_id") in data.doc_ids]

    if not docs:
        return {"summary": "No document context available."}

    context = "\n\n".join([d.page_content for d in docs])

    prompt = (
        "Summarize the content in 6-8 concise bullet points.\n\n"
        f"Context:\n{context}\n\n"
        "Summary:"
    )

    summary = generate_response(prompt, max_new_tokens=250)
    return {"summary": summary}


# ===============================
# NEW: COMPARE SELECTED DOCUMENTS
# ===============================
@app.post("/compare")
def compare_documents(data: CompareRequest):
    global VECTOR_STORE, DOCUMENT_REGISTRY
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

    if VECTOR_STORE is None:
        return {"comparison": "Upload documents first."}

    if len(data.doc_ids) < 2:
        return {"comparison": "Select at least 2 documents."}

    # Pull more candidates
    docs = VECTOR_STORE.similarity_search("Main topics and differences.", k=15)

    # Filter safely
    docs = [d for d in docs if d.metadata.get("doc_id") in data.doc_ids]

    if not docs:
        return {"comparison": "No comparable content found."}

    # Limit per document to avoid overload
    grouped = {}
    for d in docs:
        grouped.setdefault(d.metadata["doc_id"], []).append(d.page_content)

    context = ""
    for doc_id in data.doc_ids:
        filename = DOCUMENT_REGISTRY.get(doc_id, {}).get("filename", doc_id)
        content = "\n\n".join(grouped.get(doc_id, [])[:4])
        context += f"\n\nDocument: {filename}\n{content}\n"

    prompt = (
        "You are an expert AI that compares documents.\n"
        "Provide a detailed comparison with:\n"
        "1. Overall Themes\n"
        "2. Key Similarities\n"
        "3. Key Differences\n"
        "4. Unique Strengths per Document\n\n"
        f"{context}\n\n"
        "Comparison:"
    )

    result = generate_response(prompt, max_new_tokens=600)

    return {"comparison": result}

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