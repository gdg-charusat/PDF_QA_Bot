const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const axiosRetry = require("axios-retry").default;
const path = require("path");
const fs = require("fs");
const rateLimit = require("express-rate-limit");
const session = require("express-session");
require("dotenv").config();

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
const app = express();
app.set("trust proxy", 1);
app.use(cors());
app.use(express.json());

const upload = multer({ 
  dest: "uploads/",
  limits: { fileSize: 10 * 1024 * 1024 }, // 10MB limit
  fileFilter: (req, file, cb) => {
    if (file.mimetype === "application/pdf") {
      cb(null, true);
    } else {
      cb(new Error("Only PDF files are allowed"));
    }
  }
});
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
      maxAge: 1000 * 60 * 60 * 24, // 24 hours
    },
  })
);

// ------------------------------------------------------------------
// AXIOS RETRY CONFIG (PR FEATURE)
// ------------------------------------------------------------------
axiosRetry(axios, {
  retries: MAX_RETRY_ATTEMPTS,
  retryDelay: axiosRetry.exponentialDelay,
  retryCondition: (error) =>
    axiosRetry.isNetworkOrIdempotentRequestError(error) ||
    error.code === "ECONNABORTED" ||
    (error.response && error.response.status >= 500),
  onRetry: (retryCount, error, requestConfig) => {
    console.warn(
      `Retry ${retryCount} for ${requestConfig.url} - ${error.message}`
    );
  },
});

// ------------------------------------------------------------------
// RATE LIMITERS (MASTER FEATURE)
// ------------------------------------------------------------------
const uploadLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 5,
  message: "Too many PDF uploads, try again later",
  standardHeaders: true,
  legacyHeaders: false,
});

const askLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 30,
  message: "Too many questions, try again later",
  standardHeaders: true,
  legacyHeaders: false,
});

const summarizeLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 10,
  message: "Too many summarize requests, try again later",
  standardHeaders: true,
  legacyHeaders: false,
});

const compareLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 10,
  message: "Too many compare requests, try again later",
  standardHeaders: true,
  legacyHeaders: false,
});

// ------------------------------------------------------------------
// MULTER CONFIG
// ------------------------------------------------------------------
const upload = multer({ dest: "uploads/" });

// ------------------------------------------------------------------
// ROUTE: UPLOAD PDF
// ------------------------------------------------------------------
app.post("/upload", uploadLimiter, upload.single("file"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    const filePath = path.join(__dirname, req.file.path);
    
    // Check if file is empty
    const stats = fs.statSync(filePath);
    if (stats.size === 0) {
      fs.unlinkSync(filePath); // Clean up
      return res.status(400).json({ error: "Uploaded PDF file is empty" });
    }

    // Verify PDF header
    const buffer = Buffer.alloc(5);
    const fd = fs.openSync(filePath, 'r');
    fs.readSync(fd, buffer, 0, 5, 0);
    fs.closeSync(fd);
    
    if (buffer.toString() !== '%PDF-') {
      fs.unlinkSync(filePath); // Clean up
      return res.status(400).json({ error: "File is not a valid PDF" });
    }

    const response = await axios.post("http://localhost:5000/process-pdf", {
      filePath,
    });
      return res.status(400).json({
        error: "No file uploaded. Use form field name 'file'.",
      });
    }

    const sessionId = req.body.sessionId;
    if (!sessionId) {
      return res.status(400).json({ error: "Missing sessionId." });
    }

    const filePath = path.join(__dirname, req.file.path);

    const response = await axios.post(
      "http://localhost:5000/process-pdf",
      { filePath, session_id: sessionId },
      { timeout: API_REQUEST_TIMEOUT }
    );

    res.json({ message: "PDF uploaded & processed successfully" });
  } catch (err) {
    // Clean up file if it exists
    if (req.file) {
      const filePath = path.join(__dirname, req.file.path);
      if (fs.existsSync(filePath)) {
        fs.unlinkSync(filePath);
      }
    }
    
    if (err.message === "Only PDF files are allowed") {
      return res.status(400).json({ error: err.message });
    }
    
    const errorMsg = err.response?.data?.error || "Upload failed. The PDF may be corrupted or unreadable.";
    res.status(500).json({ error: errorMsg });
    console.error("Upload failed:", err.response?.data || err.message);

    if (err.code === "ECONNABORTED") {
      return res.status(504).json({
        error: "PDF processing timed out",
      });
    }

    res.status(500).json({ error: "Upload failed" });
  }
});

// ------------------------------------------------------------------
// ROUTE: ASK QUESTION
// ------------------------------------------------------------------
app.post("/ask", askLimiter, async (req, res) => {
  const { question, sessionId } = req.body;

  // ---- Input validation (PR FEATURE) ----
  if (!sessionId) {
    return res.status(400).json({ error: "Missing sessionId." });
  }

  if (!question || typeof question !== "string" || !question.trim()) {
    return res.status(400).json({ error: "Invalid question" });
  }

  if (question.length > 2000) {
    return res.status(400).json({ error: "Question too long" });
  }

  try {
    if (!req.session.chatHistory) {
      req.session.chatHistory = [];
    }

    req.session.chatHistory.push({
      role: "user",
      content: question.trim(),
    });

    const response = await axios.post(
      "http://localhost:5000/ask",
      {
        question: question.trim(),
        session_id: sessionId,
        history: req.session.chatHistory,
      },
      { timeout: API_REQUEST_TIMEOUT }
    );

    req.session.chatHistory.push({
      role: "assistant",
      content: response.data.answer,
    });

    res.json({ answer: response.data.answer });
  } catch (err) {
    console.error("Ask failed:", err.response?.data || err.message);

    if (err.code === "ECONNABORTED") {
      return res.status(504).json({ error: "Question timed out" });
    }

    res.status(500).json({ error: "Error answering question" });
  }
});

// ------------------------------------------------------------------
// ROUTE: CLEAR HISTORY
// ------------------------------------------------------------------
app.post("/clear-history", (req, res) => {
  if (req.session) {
    req.session.chatHistory = [];
  }
  res.json({ message: "History cleared" });
});

// ------------------------------------------------------------------
// ROUTE: SUMMARIZE
// ------------------------------------------------------------------
app.post("/summarize", summarizeLimiter, async (req, res) => {
  const { sessionId } = req.body || {};

  if (!sessionId) {
    return res.status(400).json({ error: "Missing sessionId." });
  }

  try {
    const response = await axios.post(
      "http://localhost:5000/summarize",
      { session_id: sessionId },
      { timeout: API_REQUEST_TIMEOUT }
    );

    res.json({ summary: response.data.summary });
  } catch (err) {
    console.error("Summarize failed:", err.response?.data || err.message);

    if (err.code === "ECONNABORTED") {
      return res.status(504).json({ error: "Summarization timed out" });
    }

    res.status(500).json({ error: "Error summarizing PDF" });
  }
});

// ------------------------------------------------------------------
// ROUTE: COMPARE
// ------------------------------------------------------------------
app.post("/compare", compareLimiter, async (req, res) => {
  try {
    const response = await axios.post(
      "http://localhost:5000/compare",
      req.body,
      { timeout: API_REQUEST_TIMEOUT }
    );
    res.json({ comparison: response.data.comparison });
  } catch (err) {
    console.error("Compare failed:", err.response?.data || err.message);
    res.status(500).json({ error: "Error comparing documents" });
  }
});

// ------------------------------------------------------------------
// START SERVER
// ------------------------------------------------------------------
app.listen(4000, () => {
  console.log("Backend running on http://localhost:4000");
});