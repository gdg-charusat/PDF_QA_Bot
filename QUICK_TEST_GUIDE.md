# Quick Testing Guide - Context Leakage Fix

## Before You Start
Ensure both services are running:
```bash
# Terminal 1: Node.js Backend
npm install  # if not done
node server.js

# Terminal 2: Python RAG Service
pip install -r requirements.txt  # if needed
python rag-service/main.py
```

## Quick Test Scripts

### Test 1: Verify Session Isolation (5 minutes)
**What it tests**: Upload different PDFs and verify only current PDF is used

```bash
# 1. Open browser and go to http://localhost:3000
# (Or use curl if preferred - see advanced tests below)

# 2. Upload Coursera Certificate
# - Use the upload form
# - Select a Coursera certificate PDF

# 3. Ask questions about Coursera
# Q: "What course is mentioned?"
# Expected: Coursera course name (e.g., "IBM Professional Certificate")
# ✓ PASS if you get Coursera-specific info

# 4. Upload NPTEL Certificate (Different PDF)
# - Use the upload form again
# - Select the NPTEL certificate PDF
# - Observe: Chat history should be cleared

# 5. Ask questions about NPTEL
# Q: "What platform issued this certificate?"
# Expected: "NPTEL"
# ✗ FAIL if it says "Coursera" or mentions old PDF
# ✓ PASS if it ONLY uses NPTEL information
```

### Test 2: Verify No Chat History Leakage (3 minutes)
**What it tests**: Previous conversation context doesn't affect new PDF

```bash
# 1. Upload PDF A (e.g., Coursera)
# 2. Ask: "Who issued this certificate?"
#    Answer: "IBM / Coursera"
# 3. Ask: "Tell me more about it"
#    Answer: References previous context (normal - same PDF)
# 4. Upload PDF B (e.g., NPTEL)
# 5. Ask: "Who issued this certificate?"
#    Expected: "NPTEL"
#    ✗ FAIL if it references Coursera or PDF A
#    ✓ PASS if it answers ONLY about PDF B
```

### Test 3: Check Status Endpoint (2 minutes)
**What it tests**: Backend state is properly tracked

```bash
# Terminal/PowerShell:

# Before uploading any PDF
curl http://localhost:4000/pdf-status
# Expected response:
# {
#   "backend": {
#     "pdf_loaded": false,
#     "session_id": null,
#     "upload_time": null
#   },
#   "frontend": { ... }
# }

# After uploading a PDF
curl http://localhost:4000/pdf-status
# Expected response:
# {
#   "backend": {
#     "pdf_loaded": true,
#     "session_id": "some-uuid-here",
#     "upload_time": "2024-02-24T..."
#   },
#   "frontend": { ... }
# }

# ✓ PASS if session_id changes between uploads
```

## Using cURL for Testing (Windows PowerShell)

### Upload PDF
```powershell
$file = "C:\path\to\your\pdf.pdf"
$form = @{
    file = Get-Item $file
}
Invoke-WebRequest -Uri "http://localhost:4000/upload" -Form $form -Method Post
```

### Ask Question
```powershell
$body = @{
    question = "What PDF is this?"
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:4000/ask" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

### Get Status
```powershell
Invoke-WebRequest -Uri "http://localhost:4000/pdf-status" -Method Get | Select-Object -ExpandProperty Content
```

### Clear History
```powershell
Invoke-WebRequest -Uri "http://localhost:4000/clear-history" -Method Post
```

## Expected Behavior After Fix

| Scenario | Before Fix | After Fix |
|----------|-----------|-----------|
| Upload PDF A, ask question | ✓ Works | ✓ Works |
| Upload PDF B immediately | ✗ Leaks PDF A context | ✓ Clears PDF A context |
| Ask about PDF B | ✗ Mixes with PDF A info | ✓ Only PDF B info |
| Session status | ✗ Not available | ✓ Available via `/status` |
| Multiple rapid uploads | ✗ Race conditions | ✓ Thread-safe |

## Troubleshooting

### Issue: Still seeing old PDF content
**Solution**: 
1. Stop both services (Ctrl+C in terminals)
2. Do NOT delete the uploads folder (file paths are used)
3. Start services again
4. Test again

### Issue: "Please upload a PDF first!" error
**This is correct!** It means the fix is working. 
- Ensure PDF was uploaded successfully
- Check browser console for errors
- Check terminal output for Python errors

### Issue: Python service not responding
**Check**:
```bash
# In Python terminal, should see:
# Uvicorn running on http://0.0.0.0:5000

# Test connectivity:
curl http://localhost:5000/status
# Should return JSON with pdf status
```

### Issue: Node.js service not responding
**Check**:
```bash
# In Node terminal, should see:
# Backend running on http://localhost:4000

# Test connectivity:
curl http://localhost:4000/pdf-status
# Should return JSON with status
```

## Success Criteria

✓ **All tests pass when**:
1. Uploading Coursera PDF returns Coursera-specific answers
2. Uploading NPTEL PDF afterwards returns ONLY NPTEL-specific answers
3. Coursera context is NOT mentioned when asking about NPTEL
4. `/pdf-status` shows different session_id for each upload
5. Chat history is empty after uploading new PDF

## What Changed Under The Hood

**Node.js (server.js)**:
- Clears chat history on new PDF upload
- Calls new `/reset` endpoint on Python service
- Stores PDF session ID in browser session

**Python (main.py)**:
- Generates unique session ID for each PDF
- Uses thread-safe locks for state management
- Validates session before answering questions
- New `/reset` endpoint explicitly clears state
- New `/status` endpoint reports current state

**No database changes needed**. Everything is in-memory with proper cleanup.

## Performance Notes
- No noticeable performance impact
- Actually improves memory usage (old vectorstores are garbage collected)
- PDF processing speed unchanged
- Question answering speed unchanged

---

**Ready to test?** Start with Test 1 (5 minutes) and you'll immediately see if the fix works!
