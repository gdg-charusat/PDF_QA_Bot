from fastapi import FastAPI, Request, File, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from dotenv import load_dotenv
import os
import uvicorn
import torch
from transformers import (
    AutoConfig,
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    AutoModelForCausalLM,
)
from uuid import uuid4
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Authentication imports
from database import engine
from auth.models import Base, User
from auth.router import router as auth_router
from auth.middleware import (
    require_upload_permission,
    require_ask_permission,
    require_summarize_permission,
    require_compare_permission,
    require_view_documents_permission,
)

load_dotenv()

app = FastAPI(
    title="PDF QA Bot API",
    description="Secure PDF Question-Answering Bot with Authentication",
    version="2.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


Base.metadata.create_all(bind=engine)
app.include_router(auth_router)


limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


VECTOR_STORE = None
DOCUMENT_REGISTRY = {}
DOCUMENT_EMBEDDINGS = {}

HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-small")

generation_tokenizer = None
generation_model = None
generation_is_encoder_decoder = False

# Embedding model
embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

class Question(BaseModel):
    question: str
    doc_ids: list[str] | None = None


class SummarizeRequest(BaseModel):
    doc_ids: list[str] | None = None


class CompareRequest(BaseModel):
    doc_ids: list[str]


def load_generation_model():
    global generation_tokenizer, generation_model, generation_is_encoder_decoder

    if generation_model is not None:
        return generation_tokenizer, generation_model, generation_is_encoder_decoder

    config = AutoConfig.from_pretrained(HF_GENERATION_MODEL)
    generation_is_encoder_decoder = bool(
        getattr(config, "is_encoder_decoder", False)
    )
    generation_tokenizer = AutoTokenizer.from_pretrained(HF_GENERATION_MODEL)

    if generation_is_encoder_decoder:
        generation_model = AutoModelForSeq2SeqLM.from_pretrained(HF_GENERATION_MODEL)
    else:
        generation_model = AutoModelForCausalLM.from_pretrained(HF_GENERATION_MODEL)

    if torch.cuda.is_available():
        generation_model = generation_model.to("cuda")

    generation_model.eval()
    return generation_tokenizer, generation_model, generation_is_encoder_decoder


def generate_response(prompt: str, max_new_tokens: int) -> str:
    tokenizer, model, is_encoder_decoder = load_generation_model()
    device = next(model.parameters()).device

    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
    encoded = {k: v.to(device) for k, v in encoded.items()}

    with torch.no_grad():
        output = model.generate(**encoded, max_new_tokens=max_new_tokens)

    if is_encoder_decoder:
        return tokenizer.decode(output[0], skip_special_tokens=True).strip()

    input_len = encoded["input_ids"].shape[1]
    new_tokens = output[0][input_len:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def process_pdf_internal(file_path: str):
    global VECTOR_STORE, DOCUMENT_REGISTRY, DOCUMENT_EMBEDDINGS

    if not os.path.exists(file_path):
        return {"error": "File not found."}

    loader = PyPDFLoader(file_path)
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=100
    )
    chunks = splitter.split_documents(docs)

    if not chunks:
        return {"error": "No text extracted from PDF."}

    # Attach doc_id metadata
    doc_id = str(uuid4())
    for chunk in chunks:
        chunk.metadata["doc_id"] = doc_id

    # Build / update vector store
    if VECTOR_STORE is None:
        VECTOR_STORE = FAISS.from_documents(chunks, embedding_model)
    else:
        VECTOR_STORE.add_documents(chunks)

    # Document registry
    filename = os.path.basename(file_path)
    DOCUMENT_REGISTRY[doc_id] = {
        "filename": filename,
        "num_chunks": len(chunks),
    }

    # Document embedding (for similarity)
    embeddings = embedding_model.embed_documents(
        [c.page_content for c in chunks]
    )
    DOCUMENT_EMBEDDINGS[doc_id] = np.mean(embeddings, axis=0)

    return {
        "message": "PDF processed successfully",
        "doc_id": doc_id,
    }


@app.post("/upload")
@limiter.limit("10/15 minutes")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_upload_permission),
):
    if not file.filename.lower().endswith(".pdf"):
        return {"error": "Only PDF files are supported"}

    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{uuid4().hex}_{file.filename}")

    try:
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        result = process_pdf_internal(file_path)
        result["uploaded_by"] = current_user.username
        return result

    except Exception as e:
        return {"error": f"Upload failed: {str(e)}"}


@app.post("/ask")
@limiter.limit("60/15 minutes")
def ask_question(
    request: Request,
    data: Question,
    current_user: User = Depends(require_ask_permission),
):
    global VECTOR_STORE

    if VECTOR_STORE is None:
        return {"answer": "Please upload at least one PDF first!"}

    docs = VECTOR_STORE.similarity_search(data.question, k=10)

    if data.doc_ids:
        docs = [
            d for d in docs if d.metadata.get("doc_id") in data.doc_ids
        ]

    if not docs:
        return {"answer": "No relevant context found."}

    context = "\n\n".join([doc.page_content for doc in docs])

    prompt = (
        "You are a helpful assistant for PDF QA.\n"
        f"Context:\n{context}\n\n"
        f"Question: {data.question}\nAnswer:"
    )

    answer = generate_response(prompt, max_new_tokens=256)
    return {"answer": answer}


@app.post("/summarize")
@limiter.limit("15/15 minutes")
def summarize_pdf(
    request: Request,
    data: SummarizeRequest,
    current_user: User = Depends(require_summarize_permission),
):
    global VECTOR_STORE

    if VECTOR_STORE is None:
        return {"summary": "Please upload a PDF first!"}

    docs = VECTOR_STORE.similarity_search(
        "Give a concise summary of the document.", k=8
    )

    if data.doc_ids:
        docs = [
            d for d in docs if d.metadata.get("doc_id") in data.doc_ids
        ]

    context = "\n\n".join([doc.page_content for doc in docs])

    prompt = (
        "Summarize the document in 6-8 bullet points.\n\n"
        f"{context}\n\nSummary:"
    )

    summary = generate_response(prompt, max_new_tokens=220)
    return {"summary": summary}


@app.post("/compare")
@limiter.limit("10/15 minutes")
def compare_documents(
    request: Request,
    data: CompareRequest,
    current_user: User = Depends(require_compare_permission),
):
    global VECTOR_STORE, DOCUMENT_REGISTRY

    if VECTOR_STORE is None:
        return {"comparison": "Upload documents first."}

    if len(data.doc_ids) < 2:
        return {"comparison": "Select at least 2 documents."}

    docs = VECTOR_STORE.similarity_search(
        "Main topics and differences.", k=15
    )
    docs = [d for d in docs if d.metadata.get("doc_id") in data.doc_ids]

    if not docs:
        return {"comparison": "No comparable content found."}

    grouped = {}
    for d in docs:
        grouped.setdefault(d.metadata["doc_id"], []).append(d.page_content)

    context = ""
    for doc_id in data.doc_ids:
        filename = DOCUMENT_REGISTRY.get(doc_id, {}).get("filename", doc_id)
        content = "\n\n".join(grouped.get(doc_id, [])[:4])
        context += f"\n\nDocument: {filename}\n{content}\n"

    prompt = (
        "Compare the documents with:\n"
        "1. Overall Themes\n2. Similarities\n3. Differences\n4. Unique Points\n\n"
        f"{context}\n\nComparison:"
    )

    result = generate_response(prompt, max_new_tokens=500)
    return {"comparison": result}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)