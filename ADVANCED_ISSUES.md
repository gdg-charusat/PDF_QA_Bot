# Advanced Issues & Technical Debt

## 🔴 Critical Issues

### 1. Multi-PDF State Corruption
**Severity**: Critical | **Component**: Backend + RAG Service

Frontend supports multiple PDFs but backend maintains single global `vectorstore`. Uploading PDF B overwrites PDF A's index.

**Impact**: Users get answers from wrong document  

**Fix**: Implement per-PDF vectorstore mapping with session IDs

### 2. Race Conditions in Concurrent Requests
**Severity**: Critical | **Component**: RAG Service

Global mutable state without thread safety. Concurrent requests corrupt vectorstore.

**Impact**: Crashes, incorrect answers  
**Fix**: Use request-scoped storage or async locks

### 3. File Path Security Vulnerability
**Severity**: Critical | **Component**: Backend

Absolute file paths exposed, no path traversal validation, files never deleted.

**Impact**: Directory traversal attacks, disk exhaustion  
**Fix**: Use UUIDs, validate paths, implement cleanup

### 4. Memory Leak from Blob URLs
**Severity**: High | **Component**: Frontend


**Impact**: Memory exhaustion after multiple uploads  
**Fix**: Add cleanup in useEffect

### 5. Cold Start Performance
**Severity**: High | **Component**: RAG Service

Model loads on first request (30s+ delay), no warmup, no timeout handling.

**Impact**: First request timeout  
**Fix**: Preload model on startup

## 🟠 Security Issues

### 6. No Rate Limiting
**Impact**: DoS attacks, resource exhaustion  
**Fix**: Add express-rate-limit middleware

### 7. Unlimited File Upload Size
**Fix**: Add `limits: { fileSize: 10 * 1024 * 1024 }`

### 8. No Input Validation
Missing validation for corrupted PDFs, malicious files, empty questions.

## 🟡 Architecture Issues

### 9. No Session Management
All users share global state, no multi-tenancy support.

### 10. Stateful Service Design
In-memory vectorstore lost on restart, cannot scale horizontally.  
**Fix**: Persist to Redis/PostgreSQL with pgvector

### 11. Context Window Truncation
Silently truncates prompts at 2048 tokens without warning.  

### 12. Fixed Retrieval Parameters
Hardcoded `k=4` chunks regardless of document size.  
**Fix**: Dynamic k based on document size

### 13. Inefficient Summarization
Uses semantic search instead of full document.  
**Fix**: Implement map-reduce summarization

## 🟢 Performance Issues

### 14. No Caching
Repeated questions re-compute embeddings and inference.

### 15. Synchronous Blocking Operations
Axios calls block event loop, no timeout configuration.  

### 16. No Model Quantization
Full precision models consume excessive memory.

## 🔵 Observability Issues

### 17. No Logging
No structured logging for debugging production issues.

### 18. No Metrics
No tracking of latency, error rates, model inference time, memory usage.

### 19. No Error Tracking
500 errors show generic alert, no error boundary.  
