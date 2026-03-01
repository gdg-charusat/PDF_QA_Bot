const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const rateLimit = require("express-rate-limit");
const session = require("express-session");
require("dotenv").config();

const app = express();

const PORT = process.env.PORT || 4000;
const RAG_URL = process.env.RAG_SERVICE_URL || "http://localhost:5000";
const SESSION_SECRET = process.env.SESSION_SECRET;

if (!SESSION_SECRET) {
  throw new Error("SESSION_SECRET must be set in environment variables");
}

app.set("trust proxy", 1);
app.use(cors());
app.use(express.json());

app.use(
  session({
    secret: SESSION_SECRET,
    resave: false,
    saveUninitialized: true,
    cookie: {
      secure: false,
      maxAge: 1000 * 60 * 60 * 24,
    },
  })
);

/* ================= RATE LIMITERS ================= */

const makeLimiter = (max, msg) =>
  rateLimit({
    windowMs: 15 * 60 * 1000,
    max,
    message: msg,
    standardHeaders: true,
    legacyHeaders: false,
  });

const uploadLimiter = makeLimiter(5, "Too many PDF uploads, try again later.");
const askLimiter = makeLimiter(30, "Too many questions, try again later.");
const summarizeLimiter = makeLimiter(10, "Too many summarization requests.");
const compareLimiter = makeLimiter(10, "Too many comparison requests.");

/* ================= UPLOAD SETUP ================= */
// Multer configuration for PDF uploads with 20MB limit and strict validation

const UPLOAD_DIR = path.resolve(__dirname, "uploads");

if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR);
}

const storage = multer.diskStorage({
  destination: (_, __, cb) => cb(null, UPLOAD_DIR),
  filename: (_, file, cb) => {
    const unique = Date.now() + "-" + file.originalname;
    cb(null, unique);
  },
});

const upload = multer({
  storage,
  limits: {
    fileSize: 20 * 1024 * 1024, // 20MB limit
  },
  fileFilter: (req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase();
    if (file.mimetype === "application/pdf" && ext === ".pdf") {
      cb(null, true);
    } else {
      cb(new Error("Invalid file type. Only PDF files are accepted."));
    }
  },
});

/* ================= HEALTH CHECKS ================= */

app.get("/healthz", (req, res) => {
  res.status(200).json({ status: "healthy", service: "pdf-qa-gateway" });
});

app.get("/readyz", async (req, res) => {
  try {
    const response = await axios.get(`${RAG_URL}/healthz`, {
      timeout: 5000,
    });

    if (response.status === 200) {
      return res.status(200).json({
        status: "ready",
        service: "pdf-qa-gateway",
        dependencies: { rag_service: "healthy" },
      });
// Route: Upload PDF
app.post("/upload", upload.single("file"), async (req, res) => {
  let filePath = null;

  try {
    // Check if file was uploaded
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded. Use form field name 'file'." });
    }

    throw new Error("RAG unhealthy");
  } catch (error) {
    return res.status(503).json({
      status: "not ready",
      service: "pdf-qa-gateway",
      dependencies: { rag_service: "unreachable" },
    });
  }
});

app.get("/health", (req, res) => {
  res.json({ status: "ok" });
});

/* ================= ROUTES ================= */

    // Build absolute file path
    filePath = path.join(__dirname, req.file.path);

    // Verify file exists on disk
    if (!fs.existsSync(filePath)) {
      return res.status(500).json({ error: "File upload failed - file not found on disk" });
    }

    console.log(`Processing PDF: ${req.file.originalname} (${req.file.size} bytes)`);

    // Send PDF to Python service for processing
    const response = await axios.post("http://localhost:5000/process-pdf", {
      filePath: filePath,
    }, {
      timeout: 60000 // 60 second timeout
    });

    res.json({
      message: "PDF uploaded & processed successfully!",
      filename: req.file.originalname,
      size: req.file.size
    });
  } catch (err) {
    // Clean up uploaded file on error
    if (filePath && fs.existsSync(filePath)) {
      try {
        fs.unlinkSync(filePath);
        console.log(`Cleaned up file after error: ${filePath}`);
      } catch (cleanupErr) {
        console.error(`Failed to cleanup file: ${cleanupErr.message}`);
      }
    }

    // Determine error type and send appropriate response
    if (err.code === 'ECONNREFUSED') {
      console.error("RAG service not available");
      return res.status(503).json({
        error: "RAG service unavailable",
        details: "Please ensure the Python service is running on port 5000"
      });
    }

    if (err.code === 'LIMIT_FILE_SIZE') {
      return res.status(413).json({
        error: "File too large",
        details: "Maximum file size is 10MB"
      });
    }

    const details = err.response?.data || err.message;
    console.error("Upload processing failed:", details);
    res.status(500).json({ error: "PDF processing failed", details });
    const filePath = path.resolve(req.file.path);
// FIX: Upload endpoint with file cleanup to prevent disk space exhaustion (Issue #110)
app.post("/upload", uploadLimiter, upload.single("file"), async (req, res) => {
  if (!req.file || !req.file.path) {
    return res.status(400).json({ error: "No file uploaded." });
  }

  const filePath = path.resolve(req.file.path);
  const uploadDirResolved = path.resolve(UPLOAD_DIR);
  
  if (!filePath.startsWith(uploadDirResolved + path.sep) && filePath !== uploadDirResolved) {
    console.error("[/upload] Path traversal attempt detected:", filePath);
    return res.status(400).json({ error: "Invalid file path." });
  }

  let fileStream;

  try {
    fileStream = fs.createReadStream(filePath);
    
  let fileStream;

  try {
    const FormData = require("form-data");
    const formData = new FormData();
    fileStream = fs.createReadStream(filePath);
    formData.append("file", fileStream, req.file.originalname);

    const response = await axios.post(
      `${RAG_URL}/upload`,
      formData,
      {
        headers: formData.getHeaders(),
        timeout: 180000,
      }
    );

    if (req.session) {
      req.session.currentSessionId = response.data.session_id;
      req.session.chatHistory = [];
    }

    return res.json({
      message: response.data.message,
      session_id: response.data.session_id,
      filename: req.file.originalname,
      size: req.file.size,
    });
  } catch (err) {
    console.error("[/upload]", err.response?.data || err.message);
    
    if (err.code === "ECONNREFUSED") {
      return res.status(503).json({
        error: "RAG service unavailable",
        details: "Please ensure the Python service is running",
      });
    }
    
    return res.status(500).json({ error: "Upload failed." });
  } finally {
    if (fileStream) {
      fileStream.destroy();
    }

    fs.unlink(filePath, (unlinkErr) => {
      if (unlinkErr && unlinkErr.code !== "ENOENT") {
        console.warn(`[/upload] Failed to delete file: ${unlinkErr.message}`);
      }
    });
  }
});


app.post("/ask", askLimiter, async (req, res) => {
  const { question, session_ids } = req.body;

  if (!question)
    return res.status(400).json({ error: "Missing question." });

  if (!session_ids || session_ids.length === 0) {
    return res
      .status(400)
      .json({ error: "Missing session_ids." });
  }

  try {
    // Initialize session chat history if it doesn't exist
    if (!req.session.chatHistory) {
      req.session.chatHistory = [];
    }

    // Add user message to session history
    req.session.chatHistory.push({
      role: "user",
      content: question,
    });

    // Send question + history to FastAPI with session isolation
    const response = await axios.post("http://localhost:5000/ask", {
      question: question,
      session_ids: session_ids,
      history: req.session.chatHistory,
    });

    // Add assistant response to session history
    req.session.chatHistory.push({
      role: "assistant",
      content: response.data.answer,
    });

    res.json(response.data);
  } catch (error) {
    console.error("[/ask]", error.response?.data || error.message);
    return res.status(500).json({ error: "Error getting answer." });
  }
  res.json({ message: "History cleared" });
});

app.post("/clear-history", (req, res) => {
  // Clear only this user's session history
  if (req.session) {
    req.session.chatHistory = [];
  }
  res.json({ message: "History cleared" });
});

app.post("/summarize", summarizeLimiter, async (req, res) => {
  const { session_ids } = req.body;

  if (!session_ids || session_ids.length === 0) {
    return res
      .status(400)
      .json({ error: "Missing session_ids." });
  }

  try {
    const response = await axios.post(
      `${RAG_URL}/summarize`,
      { session_ids },
      { timeout: 180000 }
    );

    return res.json(response.data);
  } catch (err) {
    console.error("[/summarize]", err.response?.data || err.message);
    return res
      .status(500)
      .json({ error: "Error summarizing PDF." });
  }
});

app.post("/compare", compareLimiter, async (req, res) => {
  const { session_ids } = req.body;

  if (!session_ids || session_ids.length < 2) {
    return res
      .status(400)
      .json({ error: "Select at least 2 documents." });
  }

  try {
    const response = await axios.post(
      `${RAG_URL}/compare`,
      { session_ids },
      { timeout: 180000 }
    );

    return res.json(response.data);
  } catch (err) {
    console.error("[/compare]", err.response?.data || err.message);
    return res
      .status(500)
      .json({ error: "Error comparing documents." });
  }
});

// Route: Generate Smart Question Suggestions
app.post("/generate-suggestions", async (req, res) => {
  try {
    const response = await axios.post("http://localhost:5000/suggest-questions", {}, {
      timeout: 10000
    });
    res.json({ suggestions: response.data.suggestions || [] });
  } catch (err) {
    console.error("Suggestion generation failed:", err.message);
    res.json({ suggestions: [] }); // Fail gracefully
  }
});

/* ================= GLOBAL ERROR HANDLER ================= */

app.use((err, req, res, next) => {
  if (err instanceof multer.MulterError) {
    if (err.code === "LIMIT_FILE_SIZE") {
      return res.status(400).json({
        error: "File too large. Maximum allowed size is 20MB.",
      });
    }
    return res.status(400).json({ error: err.message });
  } else if (err) {
    return res.status(500).json({ error: err.message });
  }
  next();
});

/* ================= START SERVER ================= */

app.listen(PORT, () =>
  console.log(`Backend running on http://localhost:${PORT}`)
);
