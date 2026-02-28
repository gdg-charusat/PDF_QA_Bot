# PDF Q&A Bot

RAG-based document question-answering app with:

- **Frontend**: React app (`frontend/`)
- **Backend API**: Node + Express (`server.js`)
- **RAG Service**: FastAPI + Hugging Face + FAISS (`rag-service/`)
- **🔐 Authentication**: Role-based access control with JWT tokens

Upload a PDF, ask questions from its content, and generate a short summary. You can export the chat as **CSV** or **TXT** (plain text).

---

## 🚀 Important: Context Leakage Fix Implemented

**Issue Resolved**: The system previously showed content from old PDFs when answering questions about new PDFs. This has been **completely fixed**.

**For testing and understanding the fix**, see:
- 📖 [START_HERE.md](START_HERE.md) - Quick start (5 minutes)
- 🧪 [QUICK_TEST_GUIDE.md](QUICK_TEST_GUIDE.md) - Testing procedures
- 📋 [CONTEXT_LEAKAGE_FIX.md](CONTEXT_LEAKAGE_FIX.md) - Technical details
- 📝 [SOLUTION_SUMMARY.md](SOLUTION_SUMMARY.md) - Complete overview

---

⚠️ **SECURITY NOTE**: As of v2.0.0, authentication is required for all PDF processing endpoints. See [Authentication](#authentication) section below.

## Architecture

1. Frontend uploads file to Node backend (`/upload`)
2. Node forwards file path to FastAPI (`/process-pdf`)
3. FastAPI detects file format (`.pdf`, `.docx`, `.txt`, `.md`), loads and splits the document, builds vector index with embeddings
4. For `/ask` and `/summarize`, FastAPI retrieves relevant chunks and generates output with a Hugging Face model
5. **🔐 All API endpoints now require valid JWT authentication**

---

## 📄 Page-Level Citations

Every answer from the `/ask` endpoint now includes a `citations` array that tells you **exactly which page(s)** of which PDF the answer was retrieved from.

### How it works

| Step | What happens |
|------|-------------|
| **Upload** | `PyPDFLoader` loads the PDF and assigns a `page` index (0-based) to every chunk. `RecursiveCharacterTextSplitter` preserves that metadata when splitting. |
| **Retrieval** | `similarity_search` returns the top-K most relevant chunks, each carrying its `page` metadata. |
| **Context building** | Each retrieved chunk is prefixed with `[Page N]` before being sent to the generation model, so the model is page-aware. |
| **Response** | The API returns both the generated `answer` and a sorted, deduplicated `citations` list. |

### API response format

```json
{
  "answer": "The contract was signed on January 1st, 2024.",
  "citations": [
    { "page": 3, "source": "contract_2024.pdf" },
    { "page": 7, "source": "contract_2024.pdf" }
  ]
}
```

- `page` — **1-indexed** page number (page 1 = first page of the PDF).
- `source` — original filename of the uploaded PDF.
- The list is sorted by `source` then `page`, and deduplicated (one entry per unique page per file).

### Frontend display

Citation badges are shown below each bot answer in the chat UI:

```
Bot: The contract was signed on January 1st, 2024.
  📄 contract_2024.pdf — p.3   📄 contract_2024.pdf — p.7
```

### Running citation tests

```bash
cd rag-service
pytest tests/test_citations.py -v
```

---


## Project Structure

```text
.
├── frontend/           # React UI
├── rag-service/        # FastAPI RAG service
│   ├── auth/           # Authentication system
│   │   ├── models.py   # User models & roles
│   │   ├── schemas.py  # Pydantic schemas
│   │   ├── security.py # JWT & password utils
│   │   ├── middleware.py # Auth middleware
│   │   └── router.py   # Auth endpoints
│   ├── tests/          # Comprehensive test suite
│   ├── database.py     # Database configuration
│   └── main.py         # FastAPI app with auth integration
├── server.js           # Node API gateway
├── uploads/            # Uploaded files (runtime)
└── CONTRIBUTING.md
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

Create `.env` in repo root (or edit existing):

```env
# Optional model override
HF_GENERATION_MODEL=google/flan-t5-base

# REQUIRED: Authentication Configuration
SECRET_KEY=your-super-secret-jwt-key-change-this-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Optional: Database Configuration (defaults to SQLite)
DATABASE_URL=sqlite:///./pdf_qa_bot.db
# For PostgreSQL: DATABASE_URL=postgresql://user:password@localhost/dbname
# For MySQL: DATABASE_URL=mysql://user:password@localhost/dbname
```

🔐 **Security Configuration Notes:**

- **`SECRET_KEY`**: MUST be changed in production! Generate with:
  ```bash
  python -c "from secrets import token_urlsafe; print(token_urlsafe(32))"
  ```
- **`DATABASE_URL`**: Defaults to SQLite for development. Use PostgreSQL/MySQL for production.
- Keep real secrets out of git.

## Authentication

### Overview

The PDF QA Bot now includes comprehensive authentication and authorization:

- **JWT-based Authentication**: Secure token-based authentication
- **Role-based Access Control**: User and Admin roles with extensible permission system
- **Password Security**: bcrypt hashing with industry-standard practices
- **API Protection**: All PDF processing endpoints require authentication

### User Roles & Permissions

| Role      | Permissions                                                                             |
| --------- | --------------------------------------------------------------------------------------- |
| **User**  | Upload PDFs, Ask questions, Summarize documents, View documents                         |
| **Admin** | All user permissions + Manage users, Delete documents, Compare documents, View all data |

### Quick Start Guide

#### 1. Create Admin User

After starting the application, create your first admin user:

```bash
# Register admin user via API
curl -X POST "http://localhost:5000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@yourcompany.com",
    "password": "your_secure_password_123",
    "full_name": "System Administrator",
    "role": "admin"
  }'
```

#### 2. Login & Get Token

```bash
# Login to get JWT token
curl -X POST "http://localhost:5000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "your_secure_password_123"
  }'

# Response:
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@yourcompany.com",
    "role": "admin",
    "is_active": true
  }
}
```

#### 3. Use Protected Endpoints

All PDF processing endpoints now require the Authorization header:

```bash
# Upload PDF with authentication
curl -X POST "http://localhost:5000/upload" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..." \
  -F "file=@your-document.pdf"

# Ask question with authentication
curl -X POST "http://localhost:5000/ask" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the main topic?",
    "doc_ids": ["doc-id-from-upload"]
  }'
```

### Authentication API Endpoints

#### Public Endpoints (No Auth Required)

- `POST /auth/register` - Register new user
- `POST /auth/login` - Login and get JWT token

#### User Endpoints (Auth Required)

- `GET /auth/me` - Get current user profile
- `PUT /auth/me` - Update current user profile
- `POST /auth/change-password` - Change password

#### Admin Endpoints (Admin Role Required)

- `GET /auth/users` - List all users
- `GET /auth/users/{user_id}` - Get user by ID
- `PUT /auth/users/{user_id}` - Update user by ID
- `DELETE /auth/users/{user_id}` - Delete user
- `POST /auth/users/{user_id}/activate` - Activate user
- `POST /auth/users/{user_id}/deactivate` - Deactivate user

### Legacy Support

For backward compatibility, a deprecated anonymous upload endpoint is available:

- `POST /upload/anonymous` - Upload without authentication (⚠️ Deprecated, will be removed)

### Frontend Integration

The React frontend automatically handles authentication:

1. **Login Flow**: Users must login before accessing features
2. **Token Management**: Automatic JWT token storage and refresh
3. **Route Protection**: Authenticated routes with role-based access
4. **User Management**: Admin interface for managing users

### Database Schema

The authentication system uses these database tables:

```sql
-- Users table
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(100),
    role VARCHAR(20) DEFAULT 'user',
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT false,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Security Best Practices

✅ **Implemented**:

- JWT tokens with configurable expiration
- bcrypt password hashing
- Role-based permission system
- Input validation and sanitization
- Rate limiting on authentication endpoints
- SQL injection prevention with SQLAlchemy ORM

🔒 **Production Recommendations**:

- Use PostgreSQL/MySQL instead of SQLite
- Configure HTTPS/TLS encryption
- Set up proper CORS policies
- Implement session management
- Add API rate limiting
- Monitor authentication logs
- Regular security audits
  HF_GENERATION_MODEL=google/flan-t5-base

````

Notes:

- `OPENAI_API_KEY` is not required for current Hugging Face RAG flow.
- Keep real secrets out of git.

## 3) Run the App (3 terminals)

### Terminal A — RAG service (port 5000)

```bash
cd rag-service
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
````

### Terminal B — Node backend (port 4000)

```bash
# from the repository root (where server.js lives)
cd <your-repo-directory>
node server.js
```

### Terminal C — Frontend (port 3000)

```bash
# navigate into the frontend subfolder from the repo root
cd frontend
npm start
```

Open: `http://localhost:3000`

## Docker Deployment

For production deployment or simplified development setup, you can use Docker Compose to run all services with proper health checks and dependency management.

### Quick Start with Docker

```bash
# Build and start all services
docker-compose up --build

# Or run in background
docker-compose up --build -d

# Check service status
docker-compose ps
```

### Health Check Verification

All services include health and readiness endpoints for monitoring and debugging:

#### Gateway Service (Node.js)

```bash
# Basic health check
curl http://localhost:4000/healthz

# Readiness check (includes RAG service connectivity)
curl http://localhost:4000/readyz
```

#### RAG Service (FastAPI)

```bash
# Basic health check
curl http://localhost:5000/healthz

# Readiness check (includes model and component status)
curl http://localhost:5000/readyz
```

#### Docker Health Status

```bash
# View service health in Docker Compose
docker-compose ps

# View health check logs
docker-compose logs gateway
docker-compose logs rag-service
```

### Service Health States

- **🟢 Healthy**: Service is up and responding
- **🟡 Starting**: Service is starting up (grace period)
- **🔴 Unhealthy**: Service failed multiple health checks

The Docker Compose setup ensures:

- RAG service starts and is healthy before gateway starts
- Gateway waits for RAG service to be ready before accepting requests
- Frontend waits for gateway to be healthy before starting
- Automatic restart on health check failures

## API Endpoints

### Node backend (`http://localhost:4000`)

- `POST /upload` (multipart form-data, field: `file`) - **🔐 Auth Required**
- `POST /ask` (`{ "question": "..." }`) - **🔐 Auth Required**
- `POST /summarize` (`{}`) - **🔐 Auth Required**

### FastAPI RAG service (`http://localhost:5000`)

#### PDF Processing Endpoints (🔐 Authentication Required)

- `POST /upload` - Upload and process PDF
- `POST /process-pdf` - Process PDF from file path
- `POST /ask` - Ask questions about documents
- `POST /summarize` - Summarize documents
- `POST /compare` - Compare multiple documents
- `GET /documents` - List processed documents
- `GET /similarity-matrix` - Get document similarity matrix
- `POST /upload` (multipart form-data, field: `file`) — accepts `.pdf`, `.docx`, `.txt`, `.md`
- `POST /ask` (`{ "question": "..." }`)
- `POST /summarize` (`{}`)

#### Authentication Endpoints (Public)

- `POST /auth/register` - Register new user
- `POST /auth/login` - Login and get JWT token

#### User Management Endpoints (🔐 Authentication Required)

- `GET /auth/me` - Get current user profile
- `PUT /auth/me` - Update profile
- `POST /auth/change-password` - Change password

#### Admin Endpoints (👑 Admin Role Required)

- `GET /auth/users` - List all users
- `GET /auth/users/{user_id}` - Get user details
- `PUT /auth/users/{user_id}` - Update user
- `DELETE /auth/users/{user_id}` - Delete user
- `POST /auth/users/{user_id}/activate` - Activate user
- `POST /auth/users/{user_id}/deactivate` - Deactivate user

#### Legacy Endpoints (⚠️ Deprecated)

- `POST /upload/anonymous` - Upload without auth (will be removed)

**Interactive API docs**: `http://localhost:5000/docs`

## Troubleshooting

### General Issues

- **`Cannot POST /upload` from frontend**
  - Restart frontend dev server after config changes: `npm start`
  - Ensure Node backend is running on port `4000`

- **Upload fails / connection refused**
  - Ensure FastAPI is running on port `5000`

- **Slow first request**
  - Hugging Face model downloads on first run (can take time)

- **Port already in use**
  - Stop old processes or change ports consistently in frontend/backend/service

### Authentication Issues

- **401 Unauthorized errors**
  - Ensure you're logged in and have a valid JWT token
  - Check that Authorization header is properly formatted: `Bearer <token>`
  - Token may have expired (default: 30 minutes) - login again

- **403 Forbidden errors**
  - Your user role may not have sufficient permissions
  - Contact admin to check your user role and permissions
  - Some endpoints require admin role

- **Database connection errors**
  - Check DATABASE_URL in .env file
  - Ensure database file has proper permissions (SQLite)
  - For PostgreSQL/MySQL: verify connection credentials

- **JWT Secret Key warnings**
  - Change SECRET_KEY in .env file from default value
  - Use a securely generated random key for production

- **User registration fails**
  - Username/email may already exist
  - Password must be at least 8 characters
  - Check required fields are filled

### Testing Authentication

Run the test suite to verify authentication is working:

```bash
cd rag-service
pip install pytest pytest-asyncio httpx pytest-mock
pytest tests/ -v
```

### Reset Database (Development)

If you need to reset the user database:

```bash
cd rag-service
rm -f pdf_qa_bot.db  # Remove SQLite database
# Database will be recreated on next startup
```

## Development Notes

- RAG index is in-memory (rebuilds after restart)
- Summarization and QA use retrieved context from the last processed PDF
- **🔐 Authentication**: SQLite database persists users across restarts
- JWT tokens expire after 30 minutes by default (configurable)
- Role-based permissions are extensible for future role types

## Testing

The project includes comprehensive test coverage for authentication and API endpoints.

### Running Tests

```bash
cd rag-service

# Install test dependencies
pip install pytest pytest-asyncio httpx pytest-mock

# Run all tests
pytest tests/ -v

# Run specific test categories
pytest tests/test_auth_endpoints.py -v  # Authentication tests
pytest tests/test_security.py -v       # Security utilities tests
pytest tests/test_middleware.py -v     # Middleware tests
pytest tests/test_models.py -v         # Database model tests
pytest tests/test_protected_endpoints.py -v  # API protection tests

# Run with coverage
pip install pytest-cov
pytest tests/ --cov=. --cov-report=html
```

### Test Categories

- **Authentication Tests**: User registration, login, token validation
- **Authorization Tests**: Role-based access control, permissions
- **Security Tests**: Password hashing, JWT token management
- **API Protection Tests**: Endpoint security, rate limiting
- **Database Tests**: User models, relationships, queries
- **Integration Tests**: End-to-end authentication flows

### Test Configuration

Tests use a separate SQLite database (`test_pdf_qa_bot.db`) that's automatically created and cleaned up. No configuration needed for basic testing.

## Security Considerations

### For Development

- Default SECRET_KEY is acceptable for local development
- SQLite database is fine for testing and development
- CORS is configured permissively for frontend integration

### For Production

⚠️ **IMPORTANT**: Before deploying to production:

1. **Change SECRET_KEY**: Generate a secure random key
2. **Use Production Database**: PostgreSQL or MySQL recommended
3. **Configure CORS**: Restrict allowed origins to your domain
4. **Enable HTTPS**: Use TLS encryption for all communications
5. **Environment Variables**: Use proper secrets management
6. **Update Dependencies**: Keep all packages up to date
7. **Rate Limiting**: Configure appropriate rate limits
8. **Monitoring**: Set up authentication and error logging

### Extensibility

The authentication system is designed for future extension:

- **Additional Roles**: Easy to add MODERATOR, PREMIUM_USER, etc.
- **Custom Permissions**: Granular permission system expandable
- **OAuth Integration**: Architecture supports OAuth2/OIDC providers
- **Multi-tenant**: Database schema ready for organization support
- **Audit Logging**: Framework in place for comprehensive audit trails

## Advanced Issues

See [ADVANCED_ISSUES.md](ADVANCED_ISSUES.md) for critical security, performance, and architecture issues that need attention before production deployment.

## Contributing

Refer to [CONTRIBUTING.md](CONTRIBUTING.md) for detailed instructions on creating a branch, naming conventions, committing changes, and submitting pull requests.
