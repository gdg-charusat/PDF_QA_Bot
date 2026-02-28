const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const rateLimit = require("express-rate-limit");
const session = require("express-session");
require("dotenv").config();

const app = express(); // FIX: removed duplicate declaration


const PORT = process.env.PORT || 4000;
const RAG_URL = process.env.RAG_SERVICE_URL || "http://localhost:5000";
const SESSION_SECRET = process.env.SESSION_SECRET; // FIX: removed hardcoded secret

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

const upload = multer({ storage });


app.get("/healthz", (req, res) => {
  res.status(200).json({ status: "healthy", service: "pdf-qa-gateway" });
});

app.get("/readyz", async (req, res) => {
  try {
    const response = await axios.get(`${RAG_URL}/healthz`, { timeout: 5000 });
    if (response.status === 200) {
      return res.status(200).json({
        status: "ready",
        service: "pdf-qa-gateway",
        dependencies: { rag_service: "healthy" },
      });
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

// FIX: Upload endpoint with file cleanup to prevent disk space exhaustion (Issue #110)
app.post("/upload", uploadLimiter, upload.single("file"), async (req, res) => {
  // Guard against missing file to avoid accessing properties of undefined
  if (!req.file || !req.file.path) {
    return res.status(400).json({ error: "No file uploaded." });
  }

  const filePath = path.resolve(req.file.path);
  const uploadDirResolved = path.resolve(UPLOAD_DIR);
  
  // SECURITY: Validate that the file path is within UPLOAD_DIR (prevent path traversal)
  if (!filePath.startsWith(uploadDirResolved + path.sep) && filePath !== uploadDirResolved) {
    console.error("[/upload] Path traversal attempt detected:", filePath);
    return res.status(400).json({ error: "Invalid file path." });
  }

  let fileStream;

app.post("/upload", uploadLimiter, upload.single("file"), async (req, res) => {
  try {
    const formData = new FormData();
    const fileStream = fs.createReadStream(req.file.path);
  try {
    const formData = new (require('form-data'))();
    const fileStream = fs.createReadStream(req.file.path);
    formData.append("file", fileStream);
    const realIp = req.headers["x-real-ip"] || req.ip;
    const response = await axios.post(
      `${RAG_URL}/upload`,
      formData,
      {
        headers: {
          ...formData.getHeaders(),
          "X-Real-IP": realIp
        },
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
    });
  } catch (err) {
    console.error("[/upload]", err.response?.data || err.message);
    return res.status(500).json({ error: "Upload failed." });
  } finally {
    // SECURITY: Destroy stream to prevent file descriptor leaks (especially on Windows)
    if (fileStream) {
      fileStream.destroy();
    }
    
    // FIX: Delete uploaded file from Node server after processing (Issue #110)
    // This prevents disk space exhaustion from orphaned PDF files
    fs.unlink(filePath, (unlinkErr) => {
      if (unlinkErr && unlinkErr.code !== "ENOENT") {
        // Only log if it's not "file not found" (which is fine)
        console.warn(`[/upload] Failed to delete file: ${unlinkErr.message}`);
      }
    });
  }
});


app.post("/ask", askLimiter, async (req, res) => {
  const { question, session_ids } = req.body;

  if (!question) return res.status(400).json({ error: "Missing question." });
  if (!session_ids || session_ids.length === 0) {
    return res.status(400).json({ error: "Missing session_ids." });
  }

  try {
    const realIp = req.headers["x-real-ip"] || req.ip;
    const response = await axios.post(
      `${RAG_URL}/ask`,
      { question, session_ids },
      {
        timeout: 180000,
        headers: { "X-Real-IP": realIp }
      }
    );

    return res.json(response.data);
  } catch (error) {
    console.error("[/ask]", error.response?.data || error.message);
    return res.status(500).json({ error: "Error getting answer." });
  }
});


app.post("/summarize", summarizeLimiter, async (req, res) => {
  const { session_ids } = req.body;

  if (!session_ids || session_ids.length === 0) {
    return res.status(400).json({ error: "Missing session_ids." });
  }

  try {
    const realIp = req.headers["x-real-ip"] || req.ip;
    const response = await axios.post(
      `${RAG_URL}/summarize`,
      { session_ids },
      {
        timeout: 180000,
        headers: { "X-Real-IP": realIp }
      }
    );

    return res.json(response.data);
  } catch (err) {
    console.error("[/summarize]", err.response?.data || err.message);
    return res.status(500).json({ error: "Error summarizing PDF." });
  }
});


app.post("/compare", compareLimiter, async (req, res) => {
  const { session_ids } = req.body;

  if (!session_ids || session_ids.length < 2) {
    return res.status(400).json({ error: "Select at least 2 documents." });
  }

  try {
    const realIp = req.headers["x-real-ip"] || req.ip;
    const response = await axios.post(
      `${RAG_URL}/compare`,
      { session_ids },
      {
        timeout: 180000,
        headers: { "X-Real-IP": realIp }
      }
    );

    return res.json(response.data);
  } catch (err) {
    console.error("[/compare]", err.response?.data || err.message);
    return res.status(500).json({ error: "Error comparing documents." });
  }
});


app.get("/health", (req, res) => {
  res.json({ status: "ok" });
});

app.listen(PORT, () =>
  console.log(`Backend running on http://localhost:${PORT}`)
);