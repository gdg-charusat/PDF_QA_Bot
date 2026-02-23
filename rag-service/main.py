from fastapi import FastAPI, Query
from pydantic import BaseModel
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from dotenv import load_dotenv
import os
import uvicorn
import torch
from transformers import AutoConfig, AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM
from uuid import uuid4
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

load_dotenv()

app = FastAPI()

# ===============================
# SESSION-SCOPED STATE
# ===============================
# Each session gets its own isolated vector store, document registry,
# and document embeddings to prevent cross-user data leakage.
# Structure: { session_id: { "vector_store": FAISS|None, "registry": {}, "embeddings": {} } }
SESSION_STORES: dict[str, dict] = {}


def get_session(session_id: str) -> dict:
    """Get or create an isolated session store for the given session_id."""
    if session_id not in SESSION_STORES:
        SESSION_STORES[session_id] = {
            "vector_store": None,
            "registry": {},
            "embeddings": {},
        }
    return SESSION_STORES[session_id]


HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-small")

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
        return generation_tokenizer, generation_model, generation_is_encoder_decoder

    config = AutoConfig.from_pretrained(HF_GENERATION_MODEL)
    generation_is_encoder_decoder = bool(getattr(config, "is_encoder_decoder", False))
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
    pad_token_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    with torch.no_grad():
        output_ids = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=pad_token_id,
        )

    if is_encoder_decoder:
        return tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()

    input_len = encoded["input_ids"].shape[1]
    new_tokens = output_ids[0][input_len:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


# ===============================
# REQUEST MODELS
# ===============================
class PDFPath(BaseModel):
    filePath: str
    session_id: str


class Question(BaseModel):
    question: str
    session_id: str
    doc_ids: list[str] | None = None


class SummarizeRequest(BaseModel):
    session_id: str
    doc_ids: list[str] | None = None


class CompareRequest(BaseModel):
    session_id: str
    doc_ids: list[str]


class CleanupRequest(BaseModel):
    session_id: str


# ===============================
# PROCESS PDF (SESSION-SCOPED)
# ===============================
@app.post("/process-pdf")
def process_pdf(data: PDFPath):
    session = get_session(data.session_id)

    if not os.path.exists(data.filePath):
        return {"error": "File not found."}

    loader = PyPDFLoader(data.filePath)
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100
    )
    chunks = splitter.split_documents(docs)

    if not chunks:
        return {"error": "No text chunks generated from the PDF."}

    doc_id = str(uuid4())
    filename = os.path.basename(data.filePath)

    for chunk in chunks:
        chunk.metadata = {
            "doc_id": doc_id,
            "filename": filename
        }

    if session["vector_store"] is None:
        session["vector_store"] = FAISS.from_documents(chunks, embedding_model)
    else:
        session["vector_store"].add_documents(chunks)

    embeddings = embedding_model.embed_documents(
        [c.page_content for c in chunks]
    )
    doc_vector = np.mean(embeddings, axis=0)
    session["embeddings"][doc_id] = doc_vector

    session["registry"][doc_id] = {
        "filename": filename,
        "num_chunks": len(chunks)
    }

    return {
        "message": "PDF processed successfully",
        "doc_id": doc_id
    }


# ===============================
# LIST DOCUMENTS (SESSION-SCOPED)
# ===============================
@app.get("/documents")
def list_documents(session_id: str = Query(...)):
    session = get_session(session_id)
    return session["registry"]


# ===============================
# SIMILARITY MATRIX (SESSION-SCOPED)
# ===============================
@app.get("/similarity-matrix")
def similarity_matrix(session_id: str = Query(...)):
    session = get_session(session_id)

    if len(session["embeddings"]) < 2:
        return {"error": "At least 2 documents required."}

    doc_ids = list(session["embeddings"].keys())
    vectors = np.array([session["embeddings"][d] for d in doc_ids])
    sim_matrix = cosine_similarity(vectors)

    result = {}
    for i, doc_id in enumerate(doc_ids):
        result[doc_id] = {}
        for j, other_id in enumerate(doc_ids):
            result[doc_id][other_id] = float(sim_matrix[i][j])

    return result


# ===============================
# ASK QUESTION (SESSION-SCOPED)
# ===============================
@app.post("/ask")
def ask_question(data: Question):
    session = get_session(data.session_id)

    if session["vector_store"] is None:
        return {"answer": "Please upload at least one PDF first!"}

    docs = session["vector_store"].similarity_search(data.question, k=10)

    if data.doc_ids:
        docs = [d for d in docs if d.metadata.get("doc_id") in data.doc_ids]

    if not docs:
        return {"answer": "No relevant context found."}

    context = "\n\n".join([d.page_content for d in docs])

    if data.doc_ids and len(data.doc_ids) > 1:
        prompt = (
            "You are an AI assistant comparing multiple documents.\n"
            "Clearly structure your answer as:\n"
            "- Similarities\n"
            "- Differences\n"
            "- Unique points per document\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {data.question}\n"
            "Answer:"
        )
    else:
        prompt = (
            "You are a helpful assistant answering questions about a PDF.\n"
            "Use ONLY the provided context.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {data.question}\n"
            "Answer:"
        )

    answer = generate_response(prompt, max_new_tokens=300)
    return {"answer": answer}


# ===============================
# SUMMARIZE (SESSION-SCOPED)
# ===============================
@app.post("/summarize")
def summarize_pdf(data: SummarizeRequest):
    session = get_session(data.session_id)

    if session["vector_store"] is None:
        return {"summary": "Please upload at least one PDF first!"}

    docs = session["vector_store"].similarity_search("Summarize the document.", k=12)

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
# COMPARE DOCUMENTS (SESSION-SCOPED)
# ===============================
@app.post("/compare")
def compare_documents(data: CompareRequest):
    session = get_session(data.session_id)

    if session["vector_store"] is None:
        return {"comparison": "Upload documents first."}

    if len(data.doc_ids) < 2:
        return {"comparison": "Select at least 2 documents."}

    # Pull more candidates
    docs = session["vector_store"].similarity_search("Main topics and differences.", k=15)

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
        filename = session["registry"].get(doc_id, {}).get("filename", doc_id)
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


# ===============================
# CLEANUP SESSION
# ===============================
@app.post("/cleanup-session")
def cleanup_session(data: CleanupRequest):
    """Remove all data associated with a session to free memory."""
    if data.session_id in SESSION_STORES:
        del SESSION_STORES[data.session_id]
        return {"message": f"Session {data.session_id} cleaned up."}
    return {"message": "Session not found."}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000)