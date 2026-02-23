from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
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
from slowapi import Limiter
from slowapi.util import get_remote_address
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError

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

HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-base")

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


class Question(BaseModel):
    question: str
    doc_ids: list[str] | None = None


class SummarizeRequest(BaseModel):
    doc_ids: list[str] | None = None


class CompareRequest(BaseModel):
    doc_ids: list[str]


# ===============================
# PROCESS PDF (MULTI-DOC SUPPORT)
# ===============================
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


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)