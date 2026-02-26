const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const axiosRetry = require("axios-retry").default;
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const rateLimit = require("express-rate-limit");
const { fileTypeFromFile } = require("file-type");

const app = express(); // Trust first proxy for rate limiting if behind a proxy
const session = require("express-session");
require("dotenv").config();

const app = express();

// ------------------------------------------------------------------
// CONFIGURATION
// ------------------------------------------------------------------
const API_REQUEST_TIMEOUT = parseInt(
  process.env.API_REQUEST_TIMEOUT || "45000",
  10
);

const MAX_RETRY_ATTEMPTS = parseInt(
  process.env.MAX_RETRY_ATTEMPTS || "3",
  10
);

// ------------------------------------------------------------------
// APP SETUP
// ------------------------------------------------------------------
app.set("trust proxy", 1);
app.use(cors());
app.use(express.json());

// ------------------------------------------------------------------
// SESSION (per-user chat history)
// ------------------------------------------------------------------
app.use(
  session({
    secret: "pdf-qa-bot-secret-key",
    resave: false,
    saveUninitialized: true,
    cookie: {
      secure: false,
      maxAge: 1000 * 60 * 60 * 24,
    },
  })
);

// ---------------------------------------------------------------------------
// Rate limiters
// ---------------------------------------------------------------------------
const makeLimiter = (max, msg) =>
  rateLimit({
    windowMs: 15 * 60 * 1000,
    max,
    message: msg,
    standardHeaders: true,
    legacyHeaders: false,
    validate: { xForwardedForHeader: false },
  });

const uploadLimiter = makeLimiter(5, "Too many PDF uploads, please try again after 15 minutes.");
const askLimiter = makeLimiter(30, "Too many questions, please try again after 15 minutes.");
const summarizeLimiter = makeLimiter(10, "Too many summarization requests, please try again after 15 minutes.");
const compareLimiter = makeLimiter(10, "Too many comparison requests, please try again after 15 minutes.");

// ------------------------------------------------------------------
// FILE STORAGE
// ------------------------------------------------------------------
const UPLOAD_DIR = path.resolve(__dirname, "uploads");

// RAG service base URL (Python FastAPI)
const RAG_URL = "http://localhost:5000";

// Common timeout for all RAG calls (3 minutes)
const RAG_TIMEOUT = 180_000;

// ---------------------------------------------------------------------------
// POST /upload  — upload a PDF and get back a doc_id
// ---------------------------------------------------------------------------
app.post("/upload", uploadLimiter, upload.single("file"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded. Use form field name 'file'." });
    }

    const { sessionId } = req.body;
    if (!sessionId) {
      return res.status(400).json({ error: "Missing sessionId." });
    }

    // **CRITICAL**: Clear session and reset backend state before processing new PDF
    // This prevents cross-document context leakage
    if (req.session) {
      req.session.chatHistory = [];
      req.session.currentPdfSessionId = null;
    }

    // Reset backend state through the /reset endpoint
    try {
      await axios.post("http://localhost:5000/reset");
    } catch (resetError) {
      console.warn("Warning: Could not reset backend state:", resetError.message);
      // Continue with PDF upload even if reset fails
    }

    const response = await axios.post(
      `${RAG_URL}/process-pdf`,
      { filePath, session_id: sessionId },
      { timeout: RAG_TIMEOUT }
    );

    // Forward the doc_id that Python assigned to this PDF
    return res.json({
      message: response.data.message || "PDF processed successfully",
      doc_id: response.data.doc_id,
    });
  } catch (err) {
    console.error("[/upload]", err.response?.data || err.message);
    return res.status(500).json({ error: "Upload failed. Please try again." });
  }
});

// ---------------------------------------------------------------------------
// POST /ask  — ask a question across one or more selected documents
// ---------------------------------------------------------------------------
app.post("/ask", askLimiter, async (req, res) => {
  const { question, sessionId, doc_ids } = req.body;

  if (!sessionId) return res.status(400).json({ error: "Missing sessionId." });
  if (!question || !question.trim()) return res.status(400).json({ error: "Missing question." });

  try {
    if (!req.session.chatHistory) req.session.chatHistory = [];

    req.session.chatHistory.push({ role: "user", content: question });

    const response = await axios.post(
      `${RAG_URL}/ask`,
      {
        question,
        session_id: sessionId,
        doc_ids: Array.isArray(doc_ids) ? doc_ids : [],
        history: req.session.chatHistory.slice(-10), // last 10 turns
      },
      { timeout: RAG_TIMEOUT }
    );

    req.session.chatHistory.push({ role: "assistant", content: response.data.answer });

    return res.json(response.data);
  } catch (error) {
    console.error("[/ask]", error.response?.data || error.message);
    return res.status(500).json({ error: "Error getting answer. Please try again." });
  }
});

// ---------------------------------------------------------------------------
// POST /clear-history  — wipe this user's chat history
// ---------------------------------------------------------------------------
app.post("/clear-history", (req, res) => {
  if (req.session) req.session.chatHistory = [];
  res.json({ message: "History cleared" });
});

// ---------------------------------------------------------------------------
// POST /summarize  — summarize one or more selected documents
// ---------------------------------------------------------------------------
app.post("/summarize", summarizeLimiter, async (req, res) => {
  const { sessionId, doc_ids } = req.body || {};
  if (!sessionId) return res.status(400).json({ error: "Missing sessionId." });

  try {
    const response = await axios.post(
      `${RAG_URL}/summarize`,
      {
        session_id: sessionId,
        doc_ids: Array.isArray(doc_ids) ? doc_ids : [],
      },
      { timeout: RAG_TIMEOUT }
    );
    return res.json({ summary: response.data.summary });
  } catch (err) {
    console.error("[/summarize]", err.response?.data || err.message);
    return res.status(500).json({ error: "Error summarizing PDF. Please try again." });
  }
});

// ---------------------------------------------------------------------------
// POST /compare  — compare two or more selected documents
// ---------------------------------------------------------------------------
app.post("/compare", compareLimiter, async (req, res) => {
  const { sessionId, doc_ids } = req.body || {};
  if (!sessionId) return res.status(400).json({ error: "Missing sessionId." });
  if (!Array.isArray(doc_ids) || doc_ids.length < 2) {
    return res.status(400).json({ error: "Please select at least 2 documents to compare." });
  }

  try {
    const response = await axios.post(
      `${RAG_URL}/compare`,
      { session_id: sessionId, doc_ids },
      { timeout: RAG_TIMEOUT }
    );
    return res.json({ comparison: response.data.comparison });
  } catch (err) {
    console.error("[/compare]", err.response?.data || err.message);
    return res.status(500).json({ error: "Error comparing documents. Please try again." });
  }
  next(err);
});

// ---------------------------------------------------------------------------
// GET /health
// ---------------------------------------------------------------------------
app.get("/health", (req, res) => res.json({ status: "ok" }));

app.listen(4000, () => console.log("Backend running on http://localhost:4000"));
