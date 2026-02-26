const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const fs = require("fs");
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

const session = require("express-session");
require("dotenv").config();

const app = express(); // FIX: removed duplicate declaration


const PORT = process.env.PORT || 4000;
const RAG_URL = process.env.RAG_SERVICE_URL || "http://localhost:5000";
const SESSION_SECRET = process.env.SESSION_SECRET; // FIX: removed hardcoded secret

if (!SESSION_SECRET) {
  throw new Error("SESSION_SECRET must be set in environment variables");
}




/* ======================================================
   APP SETUP
====================================================== */

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


app.post("/upload", uploadLimiter, upload.single("file"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded." });
    }

    const formData = new FormData();
    const fileStream = fs.createReadStream(req.file.path);

    const response = await axios.post(
      `${RAG_URL}/upload`,
      formData.append("file", fileStream),
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 180000,
      }
    );

    // Store sessionId returned from FastAPI
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
  }
});


app.post("/ask", askLimiter, async (req, res) => {
  const { question, session_ids } = req.body;

  if (!question) return res.status(400).json({ error: "Missing question." });
  if (!session_ids || session_ids.length === 0) {
    return res.status(400).json({ error: "Missing session_ids." });
  }

  try {

    const response = await axios.post(
      `${RAG_URL}/ask`,
      { question, session_ids },
      { timeout: 180000 }
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
    const sessionId = req.sessionID;

    const response = await axios.post(
      `${RAG_URL}/summarize`,
      { session_ids },
      { timeout: 180000 }
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
});


/* ======================================================
   CLEAR HISTORY
====================================================== */
app.post("/clear-history", (req, res) => {
  if (req.session) {
    req.session.chatHistory = [];

  try {
    const response = await axios.post(
      `${RAG_URL}/compare`,
      { session_ids },
      { timeout: 180000 }
    );

    return res.json(response.data);
  } catch (err) {
    console.error("[/compare]", err.response?.data || err.message);
    return res.status(500).json({ error: "Error comparing documents." });

  }
  res.json({ message: "History cleared" });
});


/* ======================================================
   START SERVER
====================================================== */
app.listen(4000, () =>
  console.log("Backend running on http://localhost:4000")


app.get("/health", (req, res) => {
  res.json({ status: "ok" });
});

app.listen(PORT, () =>
  console.log(`Backend running on http://localhost:${PORT}`)

);