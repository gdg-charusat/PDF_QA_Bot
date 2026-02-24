# PDF QA Bot - Complete Setup & Run Guide

## Architecture
Your application has 3 main components running on different ports:
- **Frontend (React)**: Port 3000 - User interface
- **Backend (Node.js/Express)**: Port 4000 - API server
- **Python RAG Service (FastAPI)**: Port 5000 - PDF processing & Q&A

## Key Fixes Applied
1. ✅ **React-PDF CSS imports added** - Fixed TextLayer and AnnotationLayer warnings
2. ✅ **Improved error handling** - Better error messages for debugging
3. ✅ **Connectivity improvements** - Proper timeouts and error detection

---

## Step-by-Step Setup

### 1. Install Frontend Dependencies
```bash
cd frontend
npm install
```

### 2. Install Backend Dependencies
```bash
npm install
```
(from root directory)

### 3. Setup Python Service
```bash
cd rag-service
pip install -r requirements.txt
```

---

## Running the Application (3 Separate Terminals)

### Terminal 1: Start Python RAG Service (MUST RUN FIRST)
```bash
cd rag-service
python -m uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```
**Expected output:**
```
INFO:     Uvicorn running on http://0.0.0.0:5000
INFO:     Application startup complete
```

### Terminal 2: Start Backend Server
```bash
node server.js
```
**Expected output:**
```
Backend running on http://localhost:4000
```

### Terminal 3: Start Frontend
```bash
cd frontend
npm start
```
**Expected output:**
```
Compiled successfully!
On Your Network:  http://192.168.x.x:3000
```

---

## Troubleshooting

### Error: "Python service is not running on port 5000"
- ✅ Make sure you started the Python service in Terminal 1 first
- ✅ Check that port 5000 is not in use: `netstat -ano | findstr :5000` (Windows)

### Error: "TextLayer styles not found"
- ✅ Already fixed! React-PDF CSS imports have been added
- ✅ Clear browser cache and refresh: `Ctrl+Shift+Delete`

### Error: "Cannot reach Python service"
- ✅ Ensure Python service is running on `localhost:5000`
- ✅ Check firewall settings allow localhost connections
- ✅ Verify no other process is using port 5000

### Upload fails with "Upload processing failed"
- ✅ This means the Python service died or crashed
- ✅ Check Terminal 1 for error messages
- ✅ Python service may need GPU/dependencies - check requirements

### Port Already in Use
```bash
# Windows - Kill process on port 3000
taskkill /PID <PID_NUMBER> /F

# Windows - Kill process on port 4000
taskkill /PID <PID_NUMBER> /F

# Windows - Kill process on port 5000
taskkill /PID <PID_NUMBER> /F
```

---

## Testing the Application

1. Open http://localhost:3000 in your browser
2. You should see no console errors about TextLayer/AnnotationLayer
3. Upload a PDF file
4. Type a question and get an answer
5. Check all three terminal windows for logs

---

## Environment Variables (Optional)

Create a `.env` file in the root and `rag-service` directories if needed:

**Root/.env:**
```
REACT_APP_API_URL=http://localhost:4000
```

**rag-service/.env:**
```
HF_GENERATION_MODEL=google/flan-t5-base
```

---

## Performance Tips

- **First run** takes longer due to model downloads
- **Large PDFs** may take 30+ seconds to process
- Keep Python service running - don't restart between uploads
- Use smaller PDFs (< 50MB) for best performance

---

## Verification Checklist

- [ ] Python service starts without errors
- [ ] Backend starts without errors  
- [ ] Frontend compiles successfully
- [ ] No console warnings about missing styles
- [ ] Can upload a PDF without "service not running" error
- [ ] Can ask a question and get an answer
