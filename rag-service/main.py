from fastapi import FastAPI, Request, HTTPException
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
from slowapi import Limiter
from slowapi.util import get_remote_address

load_dotenv()

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Temporary global variables
vectorstore = None
qa_chain = False
# For better answers, set HF_GENERATION_MODEL=google/flan-t5-large in .env (needs ~3GB RAM)
HF_GENERATION_MODEL = os.getenv("HF_GENERATION_MODEL", "google/flan-t5-base")
generation_tokenizer = None
generation_model = None
generation_is_encoder_decoder = False
_embedding_model = None


def get_embedding_model():
    """Lazy load embedding model so server starts immediately."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    return _embedding_model


def load_generation_model():
    global generation_tokenizer, generation_model, generation_is_encoder_decoder
    if generation_model is not None and generation_tokenizer is not None:
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
    model_device = next(model.parameters()).device

    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
    encoded = {key: value.to(model_device) for key, value in encoded.items()}
    pad_token_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id

    with torch.no_grad():
        generated_ids = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=pad_token_id,
        )

    if is_encoder_decoder:
        text = tokenizer.decode(generated_ids[0], skip_special_tokens=True)
        return text.strip()

    input_len = encoded["input_ids"].shape[1]
    new_tokens = generated_ids[0][input_len:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True)
    return text.strip()

class PDFPath(BaseModel):
    filePath: str

class ChatMessage(BaseModel):
    role: str
    text: str


class Question(BaseModel):
    question: str
    history: list[ChatMessage] | None = None


class SummarizeRequest(BaseModel):
    pdf: str | None = None

@app.post("/process-pdf")
@limiter.limit("15/15 minutes")
def process_pdf(request: Request, data: PDFPath):
    global vectorstore, qa_chain

    import os
    file_path = data.filePath
    if not os.path.exists(file_path):
        raise HTTPException(status_code=400, detail=f"File not found: {file_path}")

    try:
        loader = PyPDFLoader(file_path)
        docs = loader.load()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load PDF: {str(e)}")

    if not docs:
        raise HTTPException(status_code=400, detail="No text could be extracted from the PDF. The file may be empty or corrupted.")

    try:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to split document: {str(e)}")

    if not chunks:
        raise HTTPException(status_code=400, detail="No text chunks generated from the PDF. Please check your file.")

    try:
        vectorstore = FAISS.from_documents(chunks, get_embedding_model())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF (embedding): {str(e)}")

    qa_chain = True  # Just a flag to indicate PDF is processed
    return {"message": "PDF processed successfully"}


@app.post("/ask")
@limiter.limit("60/15 minutes")
def ask_question(request: Request, data: Question):
    global vectorstore, qa_chain
    if not qa_chain:
        return {"answer": "Please upload a PDF first!"}

    docs = vectorstore.similarity_search(data.question, k=6)
    if not docs:
        return {"answer": "I couldn't find relevant information in the document for your question. Try rephrasing or asking about a different topic covered in the PDF."}

    context = "\n\n".join([doc.page_content for doc in docs])

    history_text = ""
    if data.history:
        history_lines = [
            f"{'User' if m.role == 'user' else 'Assistant'}: {m.text}"
            for m in data.history[-10:]  # Last 10 messages to avoid token overflow
        ]
        history_text = (
            "Previous conversation:\n"
            + "\n".join(history_lines)
            + "\n\n"
        )

    prompt = (
        "You are a friendly, expert assistant that helps users understand their PDF documents. "
        "Give clear, helpful, and user-friendly answers. Follow these guidelines:\n"
        "- Answer in plain language; avoid jargon unless necessary\n"
        "- Structure answers with bullet points or numbered steps when listing multiple items\n"
        "- Provide actionable solutions or next steps when the user asks how to do something\n"
        "- If information is in the document, cite it; if not found, politely say so and suggest rephrasing\n"
        "- Use the previous conversation to understand follow-up questions and maintain context\n"
        "- Keep answers concise but complete; prioritize what the user needs to know\n\n"
        "Document content:\n"
        f"{context}\n\n"
        f"{history_text}"
        f"User question: {data.question}\n\n"
        "Provide a helpful, user-friendly answer:"
    )

    answer = generate_response(prompt, max_new_tokens=384)
    return {"answer": answer}


@app.post("/summarize")
@limiter.limit("15/15 minutes")
def summarize_pdf(request: Request, _: SummarizeRequest):
    global vectorstore, qa_chain
    if not qa_chain:
        return {"summary": "Please upload a PDF first!"}

    docs = vectorstore.similarity_search("Give a comprehensive summary of the document including main topics, key points, and important details.", k=8)
    if not docs:
        return {"summary": "No document content available to summarize."}

    context = "\n\n".join([doc.page_content for doc in docs])
    prompt = (
        "Create a clear, user-friendly summary of this document. Include:\n"
        "- Main topic or purpose (1-2 sentences)\n"
        "- Key points as bullet points\n"
        "- Important details, steps, or recommendations if present\n"
        "Use plain language. Make it easy for the reader to quickly understand what the document covers.\n\n"
        f"Document content:\n{context}\n\n"
        "Summary:"
    )

    summary = generate_response(prompt, max_new_tokens=320)
    return {"summary": summary}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
