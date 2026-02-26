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

# Create FastAPI app
app = FastAPI()

# Custom key function for Limiter
def real_ip_key_func(request: Request):
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip and isinstance(x_real_ip, str) and x_real_ip.count('.') == 3:
        return x_real_ip
    return request.client.host

# Limiter instance with custom key function
limiter = Limiter(key_func=real_ip_key_func)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
@app.post("/upload")
@limiter.limit("10/15 minutes")
async def upload_file(request: Request, file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(file_bytes)

        loader = PyPDFLoader(file_path)
        docs = loader.load()

        chunk_size = int(os.getenv("PDF_CHUNK_SIZE", 1000))
        chunk_overlap = int(os.getenv("PDF_CHUNK_OVERLAP", 100))
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        chunks = splitter.split_documents(docs)

        for i, chunk in enumerate(chunks):
            page_num = chunk.metadata.get("page", None)
            chunk.metadata["page_number"] = page_num
            chunk.metadata["file_name"] = file.filename

        vectorstore = FAISS.from_documents(chunks, embedding_model)

        sessions[session_id] = {
            "vectorstores": [vectorstore],
            "last_accessed": time.time()
        }

        return {
            "message": "PDF uploaded and processed",
            "session_id": session_id,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "chunks": [
                {
                    "page_content": chunk.page_content,
                    "metadata": chunk.metadata
                } for chunk in chunks[:5]
            ]
        }
    except Exception as e:
        return {"error": f"Upload failed: {str(e)}"}
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
        file_bytes = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(file_bytes)

        loader = PyPDFLoader(file_path)
        docs = loader.load()

        # Configurable chunk size and overlap
        chunk_size = int(os.getenv("PDF_CHUNK_SIZE", 1000))
        chunk_overlap = int(os.getenv("PDF_CHUNK_OVERLAP", 100))
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        # Add metadata (page number, file name) to each chunk
        chunks = splitter.split_documents(docs)
        for i, chunk in enumerate(chunks):
            # Try to get page number from source document metadata if available
            page_num = chunk.metadata.get("page", None)
            chunk.metadata["page_number"] = page_num
            chunk.metadata["file_name"] = file.filename

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

    context = "\n\n".join([d.page_content for d in docs])

    prompt = (
        "Answer the question using ONLY the provided context.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {data.question}\nAnswer:"
    )

    answer = generate_response(prompt, 200)
    return {"answer": answer}


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

    prompt = f"Summarize this document:\n\n{context}\n\nSummary:"
    summary = generate_response(prompt, 250)

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

    try:
        file_bytes = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(file_bytes)

        loader = PyPDFLoader(file_path)
        docs = loader.load()

        # Configurable chunk size and overlap
        chunk_size = int(os.getenv("PDF_CHUNK_SIZE", 1000))
        chunk_overlap = int(os.getenv("PDF_CHUNK_OVERLAP", 100))
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        chunks = splitter.split_documents(docs)

        # Ensure overlap and metadata for each chunk
        for i, chunk in enumerate(chunks):
            page_num = chunk.metadata.get("page", None)
            chunk.metadata["page_number"] = page_num
            chunk.metadata["file_name"] = file.filename

        vectorstore = FAISS.from_documents(chunks, embedding_model)

        sessions[session_id] = {
            "vectorstores": [vectorstore],
            "last_accessed": time.time()
        }

        return {
            "message": "PDF uploaded and processed",
            "session_id": session_id,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "chunks": [
                {
                    "page_content": chunk.page_content,
                    "metadata": chunk.metadata
                } for chunk in chunks[:5]  # Show first 5 chunks for verification
            ]
        }

    except Exception as e:
        return {"error": f"Upload failed: {str(e)}"}