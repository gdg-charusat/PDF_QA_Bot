# Session ID Fix - Summary

## Problem
Frontend was using a single global `sessionId` for all PDFs instead of storing and using the server-returned `sessionId` for each individual PDF.

## What Was Wrong

### Before (Broken):
```javascript
// Frontend generated its own sessionId
const [sessionId, setSessionId] = useState("");

// Sent it to backend on upload
formData.append("sessionId", sessionId);

// Used same sessionId for all PDFs
axios.post("/ask", { question, sessionId, doc_ids: selectedDocs });
```

**Result**: All PDFs shared the same sessionId, causing state corruption.

## What Was Fixed

### After (Fixed):
```javascript
// 1. Upload - Get sessionId from server response
const res = await axios.post("/upload", formData);
const serverSessionId = res.data?.sessionId;

// 2. Store sessionId per PDF
setPdfs([...prev, { 
  name: file.name, 
  sessionId: serverSessionId,  // ← Server-returned sessionId
  url 
}]);

// 3. Use stored sessionId when querying
axios.post("/ask", { 
  question, 
  sessionId: selectedDocs[0]  // ← Use PDF's sessionId
});
```

## Changes Made

### `frontend/src/App.js`:

1. **Removed global sessionId**:
   - ❌ `const [sessionId, setSessionId] = useState("")`
   - ✅ Store sessionId per PDF in `pdfs` array

2. **Upload function**:
   - ❌ `formData.append("sessionId", sessionId)`
   - ✅ `const serverSessionId = res.data?.sessionId`
   - ✅ Store in PDF object: `{ name, sessionId: serverSessionId, url }`

3. **Ask function**:
   - ❌ `sessionId: sessionId` (global)
   - ✅ `sessionId: selectedDocs[0]` (PDF-specific)

4. **Summarize function**:
   - ❌ `sessionId: sessionId` (global)
   - ✅ `sessionId: selectedDocs[0]` (PDF-specific)

5. **PDF selection**:
   - ❌ `key={pdf.doc_id}`
   - ✅ `key={pdf.sessionId}`

## Backend (Already Correct)

The backend was already correctly:
- Generating unique sessionId: `crypto.randomUUID()`
- Returning it: `res.json({ sessionId })`
- Accepting it: `const { sessionId } = req.body`
- Validating it: `if (!sessionId) return 400`

## Testing

Run the test to verify:
```bash
python test_session_fix.py
```

Expected result:
```
✓ Upload doc_A → sessionId_A
✓ Upload doc_B → sessionId_B  
✓ Query doc_A → Uses sessionId_A (correct)
✓ Query doc_B → Uses sessionId_B (correct)
✓ Query doc_A again → Still uses sessionId_A (no corruption!)
```

## Status
✅ **FIXED** - Each PDF now has its own isolated sessionId
