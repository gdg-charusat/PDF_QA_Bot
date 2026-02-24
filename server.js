const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const axiosRetry = require("axios-retry").default;
const path = require("path");
const rateLimit = require("express-rate-limit");
const { fileTypeFromFile } = require("file-type");
const fs = require("fs");
const session = require("express-session");
require("dotenv").config();

const app = express();

/* ======================================================
   CONFIGURATION
====================================================== */
const API_REQUEST_TIMEOUT = parseInt(
  process.env.API_REQUEST_TIMEOUT || "45000",
  10
);

const MAX_RETRY_ATTEMPTS = parseInt(
  process.env.MAX_RETRY_ATTEMPTS || "3",
  10
);

/* ======================================================
   APP SETUP
====================================================== */
app.set("trust proxy", 1);
app.use(cors());
app.use(express.json());

/* ======================================================
   SESSION (Per-user chat history)
====================================================== */
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

/* ======================================================
   AXIOS RETRY CONFIG
====================================================== */
axiosRetry(axios, {
  retries: MAX_RETRY_ATTEMPTS,
  retryDelay: axiosRetry.exponentialDelay,
  retryCondition: (error) =>
    axiosRetry.isNetworkOrIdempotentRequestError(error) ||
    error.code === "ECONNABORTED" ||
    (error.response && error.response.status >= 500),
});

/* ======================================================
   RATE LIMITERS
====================================================== */
const uploadLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 5,
  message: { detail: "Too many uploads. Try again later." },
  standardHeaders: true,
  legacyHeaders: false,
});

const askLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 30,
  message: { detail: "Too many questions. Try again later." },
  standardHeaders: true,
  legacyHeaders: false,
});

const summarizeLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 10,
  message: { detail: "Too many summarize requests. Try again later." },
  standardHeaders: true,
  legacyHeaders: false,
});

/* ======================================================
   UPLOAD DIRECTORY
====================================================== */
const UPLOAD_DIR = path.resolve(__dirname, "uploads");
if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR);
}

/* ======================================================
   MULTER CONFIGURATION
====================================================== */
const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];

const storage = multer.diskStorage({
  destination: "uploads/",
  filename: (req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase();
    const uniqueName = `${Date.now()}-${Math.round(
      Math.random() * 1e9
    )}${ext}`;
    cb(null, uniqueName);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 20 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase();
    if (SUPPORTED_EXTENSIONS.includes(ext)) {
      cb(null, true);
    } else {
      cb(new Error(`Unsupported file type. Allowed: ${SUPPORTED_EXTENSIONS.join(", ")}`));
    }
  },
});

/* ======================================================
   ROUTE: Upload
====================================================== */
app.post("/upload", uploadLimiter, (req, res) => {
  upload.single("file")(req, res, async (err) => {
    try {
      if (err) {
        return res.status(400).json({ detail: err.message });
      }

      if (!req.file) {
        return res.status(400).json({
          detail: "No file uploaded. Use form field name 'file'.",
        });
      }

      const filePath = path.resolve(req.file.path);

      const detectedType = await fileTypeFromFile(filePath);
      const ext = path.extname(filePath).toLowerCase();

      if (ext === ".pdf") {
        if (!detectedType || detectedType.mime !== "application/pdf") {
          fs.unlinkSync(filePath);
          return res.status(400).json({ detail: "Invalid PDF file." });
        }
      }

      const stats = fs.statSync(filePath);
      if (stats.size === 0) {
        fs.unlinkSync(filePath);
        return res.status(400).json({ detail: "Uploaded file is empty." });
      }

      const sessionId = req.sessionID;

      await axios.post(
        "http://localhost:5000/process-pdf",
        { filePath, session_id: sessionId },
        { timeout: API_REQUEST_TIMEOUT }
      );

      return res.json({
        message: "File uploaded & processed successfully!",
        sessionId,
      });
    } catch (err) {
      const status = err.response?.status || 500;
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.error ||
        err.message;

      console.error("Upload failed:", detail);

      if (req.file && fs.existsSync(req.file.path)) {
        fs.unlinkSync(req.file.path);
      }

      return res.status(status).json({ detail });
    }
  });
});

/* ======================================================
   ROUTE: Ask Question
====================================================== */
app.post("/ask", askLimiter, async (req, res) => {
  try {
    const { question, sessionId } = req.body;

    if (!sessionId) {
      return res.status(400).json({ detail: "Missing sessionId." });
    }

    if (!question || !question.trim()) {
      return res.status(400).json({ detail: "Invalid question." });
    }

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

    return res.json({ answer: response.data.answer });
  } catch (err) {
    const status = err.response?.status || 500;
    const detail =
      err.response?.data?.detail ||
      err.response?.data?.error ||
      err.message;

    console.error("Ask failed:", detail);

    return res.status(status).json({ detail });
  }
});

/* ======================================================
   ROUTE: Summarize
====================================================== */
app.post("/summarize", summarizeLimiter, async (req, res) => {
  try {
    const sessionId = req.sessionID;

    const response = await axios.post(
      "http://localhost:5000/summarize",
      { session_id: sessionId },
      { timeout: API_REQUEST_TIMEOUT }
    );

    return res.json({ summary: response.data.summary });
  } catch (err) {
    const status = err.response?.status || 500;
    const detail =
      err.response?.data?.detail ||
      err.response?.data?.error ||
      err.message;

    console.error("Summarization failed:", detail);

    return res.status(status).json({ detail });
  }
});

/* ======================================================
   CLEAR HISTORY
====================================================== */
app.post("/clear-history", (req, res) => {
  if (req.session) {
    req.session.chatHistory = [];
  }
  res.json({ message: "History cleared" });
});

/* ======================================================
   START SERVER
====================================================== */
app.listen(4000, () =>
  console.log("Backend running on http://localhost:4000")
);