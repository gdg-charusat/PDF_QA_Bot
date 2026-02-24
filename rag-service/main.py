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
from slowapi import Limiter
from slowapi.util import get_remote_address
import os
import re
import uvicorn
import time

# -------------------------------------------------------------------
# APP SETUP
# -------------------------------------------------------------------
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = (BASE_DIR / "uploads").resolve()

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# ---------------------------------------------------------------------------
# GROQ CLIENT SETUP
# ---------------------------------------------------------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Please add it to your .env file.\n"
        "Get a free key at https://console.groq.com"
    )

groq_client = Groq(api_key=GROQ_API_KEY)

# Session management
sessions = {}
SESSION_TIMEOUT = 3600  # 1 hour

embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# -------------------------------------------------------------------
# TEXT NORMALIZATION
# -------------------------------------------------------------------
def normalize_spaced_text(text: str) -> str:
    """
    Fixes character-level spaced text produced by PyPDFLoader on certain
    vector-based PDFs (e.g. NPTEL / IBM Coursera certificates).
    """
    def fix_spaced_word(match):
        return match.group(0).replace(" ", "")
    pattern = r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b"
    return re.sub(pattern, fix, text)


def normalize_answer(text: str) -> str:
    """
    Post-processes the LLM-generated answer.
    """
    text = normalize_spaced_text(text)
    # Strip only clear prompt-echo artefacts at the very start
    text = re.sub(r'^(Final Answer:|Context:|Question:)\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# CCC PROMPT TEMPLATE (Connect – Content – Continue)
# ---------------------------------------------------------------------------

_CCC_SYSTEM = (
    "You are an intelligent PDF Question Answering Assistant.\n"
    "Your task is to answer the user's question strictly using the provided context "
    "retrieved from uploaded documents.\n\n"
    "Follow the CCC communication structure in a SINGLE response:\n\n"
    "1. Context Connection — Start with a short professional greeting (e.g. \"Hello,\").\n"
    "2. Content Explanation — Rewrite the retrieved context in clear, meaningful, "
    "grammatically correct sentences. Do NOT copy text directly.\n"
    "3. Core Answer — Present the main explanation in a structured, readable format.\n"
    "4. Call to Action — End with a relevant follow-up question to encourage further exploration.\n\n"
    "Rules:\n"
    "- Use ONLY the provided context. Do NOT add external knowledge.\n"
    "- If the answer is not in the context, say: "
    "\"The uploaded document does not contain sufficient information to answer this question.\"\n"
    "- Maintain a clear, professional tone.\n"
    "- Produce one continuous response — no bullet headers like '1.' or '2.'."
)

_CCC_USER_TEMPLATE = """\
Context from the uploaded PDF:
{context}

Question:
{question}

Final Answer:"""

CCC_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=_CCC_USER_TEMPLATE,
)


# ---------------------------------------------------------------------------
# GROQ GENERATION
# ---------------------------------------------------------------------------

def generate_response(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str:
    """
    Calls the Groq chat-completions API with a system + user message pair.
    """
    completion = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return completion.choices[0].message.content.strip()


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

class SummarizeRequest(BaseModel):
    session_id: str
    pdf: str | None = None


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
# ---------------------------------------------------------------------------

@app.post("/process-pdf")
@limiter.limit("15/15 minutes")
def process_pdf(request: Request, data: DocumentPath):
    cleanup_expired_sessions()

    # Resolve and validate path (prevent path traversal)
    file_path = Path(data.filePath).resolve()

    if not str(file_path).startswith(str(UPLOAD_DIR)):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {ext}. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    try:
        raw_docs = load_document(str(file_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load document: {str(e)}")

    cleaned_docs = []
    for doc in raw_docs:
        cleaned_content = normalize_spaced_text(doc.page_content)
        cleaned_docs.append(Document(page_content=cleaned_content, metadata=doc.metadata))

    chunks = splitter.split_documents(cleaned_docs)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No text extracted from the document."
        )

    sessions[data.session_id] = {
        "vectorstore": FAISS.from_documents(chunks, embedding_model),
        "last_accessed": time.time(),
    }

    return {"message": "Document processed successfully"}

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
    for msg in history[-5:]:
        role = msg.get("role", "")
        content = msg.get("content", "")
        conversation_context += f"{role}: {content}\n"

    docs = vectorstore.similarity_search(question, k=4)
    if not docs:
        return {"answer": "No relevant context found in the uploaded document."}

    context = "\n\n".join([doc.page_content for doc in docs])

    question_with_history = question
    if conversation_context.strip():
        question_with_history = (
            f"Conversation so far:\n{conversation_context.strip()}\n\n"
            f"Current Question: {question}"
        )

    user_prompt = CCC_PROMPT.format(
        context=context,
        question=question_with_history,
    )

    raw_answer = generate_response(
        system_prompt=_CCC_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=600,
    )

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

    context = "\n\n".join([doc.page_content for doc in docs])

    system_prompt = (
        "You are a document summarization assistant.\n"
        "Rules:\n"
        "1. Summarize in 6-8 concise bullet points.\n"
        "2. Clearly state: who received the certificate/document, what it is for, "
        "which organization issued it, who authorized it, and the date.\n"
        "3. Use proper Title Case for names. Return clean, readable text.\n"
        "4. Use ONLY the information in the provided context."
    )

    user_prompt = f"Context:\n{context}\n\nSummary (bullet points):"

    raw_summary = generate_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=512
    )
    summary = normalize_answer(raw_summary)
    return {"summary": summary}


# -------------------------------------------------------------------
# START SERVER
# -------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)