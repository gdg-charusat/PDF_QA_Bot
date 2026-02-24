# PDF Q&A Bot

RAG-based PDF question-answering app with:

- **Frontend**: React app (`frontend/`)
- **Backend API**: Node + Express (`server.js`)
- **RAG Service**: FastAPI + Hugging Face + FAISS (`rag-service/`)
- **Security**: JWT-based Authentication & RBAC

Upload a PDF, ask questions from its content, and generate a short summary.

## Architecture

1. User registers/logs in via Node backend to receive a JWT token.
2. Frontend sends the token in the `Authorization` header for all protected requests.
3. Node backend verifies the token and checks user roles (User/Admin) before forwarding requests.
4. Frontend uploads file to Node backend (`/upload`).
5. Node forwards file path to FastAPI (`/process-pdf`).
6. FastAPI loads/splits PDF, builds vector index with embeddings.
7. For `/ask` and `/summarize`, FastAPI retrieves relevant chunks and generates output with a Hugging Face model.

## Project Structure

```text
.
├── frontend/           # React UI
├── rag-service/        # FastAPI RAG service
├── server.js           # Node API gateway
├── middleware/         # Auth & validation middleware
├── routes/             # Auth & functional routes
├── data/               # Persistent data (users.json)
├── uploads/            # Uploaded files (runtime)
└── test_auth.js        # Auth verification script
```

## Prerequisites

- Node.js 18+ (LTS recommended)
- Python 3.10+
- `pip`

## 1) Clone and Install Dependencies

From repository root:

```bash
npm install
cd frontend && npm install
cd ../rag-service && python -m pip install -r requirements.txt
```

## 2) Environment Variables

Create `.env` in repo root:

```env
HF_GENERATION_MODEL=google/flan-t5-base
JWT_SECRET=your_secret_key_here
```

## 3) Run the App (3 terminals)

### Terminal A — RAG service (port 5000)

```bash
cd rag-service
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```

### Terminal B — Node backend (port 4000)

```bash
node server.js
```

### Terminal C — Frontend (port 3000)

```bash
cd frontend
npm start
```

Open: `http://localhost:3000`

## API Endpoints

### Authentication (Public)
- `POST /auth/register` (`{ "email": "...", "password": "...", "role": "user|admin" }`)
- `POST /auth/login` (`{ "email": "...", "password": "..." }`) -> Returns `{ "token": "..." }`

### Protected Endpoints (Requires JWT)
- `POST /upload` (multipart form-data, field: `file`)
- `POST /ask` (`{ "question": "...", "doc_ids": [] }`)
- `POST /summarize` (`{ "doc_ids": [] }`)
- `POST /compare` (`{ "doc_ids": [] }`)

## Verification

Run the automated auth test script:
```bash
node test_auth.js
```

## Troubleshooting

- **`401 Unauthorized`**
	- Ensure you are logged in and the token is being sent in the `Authorization` header as `Bearer <token>`.
- **`403 Forbidden`**
	- Your user role does not have permission to access the requested resource.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

