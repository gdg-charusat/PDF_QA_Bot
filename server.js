const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const rateLimit = require("express-rate-limit");
const session = require("express-session");
require("dotenv").config();

const { requireAuth, requireRole } = require("./middleware/auth");

const app = express();

const PORT = process.env.PORT || 4000;
const RAG_URL = process.env.RAG_SERVICE_URL || "http://localhost:5000";
const SESSION_SECRET = process.env.SESSION_SECRET;

if (!SESSION_SECRET) {
  throw new Error("SESSION_SECRET must be set in environment variables");
}

// JWT_SECRET validation is handled inside middleware/auth.js — it throws at
// require() time if the env var is missing, so no duplicate check needed here.


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
const authLimiter = makeLimiter(20, "Too many authentication requests, try again later.");


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


// ── Health endpoints (public) ─────────────────────────────────────────────────

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

app.get("/health", (req, res) => {
  res.json({ status: "ok" });
});


// ── Auth proxy routes (public — no JWT required) ──────────────────────────────
// These forward register/login requests to the FastAPI RAG service which
// manages the user database and issues JWT tokens.

/**
 * POST /auth/register
 * Proxy → RAG_URL/auth/register
 * Body: { username, email, password, full_name?, role? }
 */
app.post("/auth/register", authLimiter, async (req, res) => {
  try {
    const response = await axios.post(
      `${RAG_URL}/auth/register`,
      req.body,
      { timeout: 10000 }
    );
    return res.status(response.status).json(response.data);
  } catch (err) {
    const status = err.response?.status || 500;
    const data = err.response?.data || { error: "Registration failed." };
    return res.status(status).json(data);
  }
});

/**
 * POST /auth/login
 * Proxy → RAG_URL/auth/login
 * Body: { username, password }
 * Returns: { access_token, token_type, expires_in, user }
 */
app.post("/auth/login", authLimiter, async (req, res) => {
  try {
    const response = await axios.post(
      `${RAG_URL}/auth/login`,
      req.body,
      { timeout: 10000 }
    );
    return res.status(response.status).json(response.data);
  } catch (err) {
    const status = err.response?.status || 500;
    const data = err.response?.data || { error: "Login failed." };
    return res.status(status).json(data);
  }
});

/**
 * GET /auth/me
 * Proxy → RAG_URL/auth/me  (forwards the Bearer token on behalf of the client)
 */
app.get("/auth/me", requireAuth, async (req, res) => {
  try {
    const authHeader = req.headers["authorization"];
    const response = await axios.get(`${RAG_URL}/auth/me`, {
      headers: { Authorization: authHeader },
      timeout: 10000,
    });
    return res.status(response.status).json(response.data);
  } catch (err) {
    const status = err.response?.status || 500;
    const data = err.response?.data || { error: "Could not fetch user profile." };
    return res.status(status).json(data);
  }
});


// ── Protected PDF endpoints (JWT required) ─────────────────────────────────────

app.post("/upload", requireAuth, uploadLimiter, upload.single("file"), async (req, res) => {
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


app.post("/ask", requireAuth, askLimiter, async (req, res) => {
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

    return res.json(response.data);
  } catch (error) {
    console.error("[/ask]", error.response?.data || error.message);
    return res.status(500).json({ error: "Error getting answer." });
  }
});


app.post("/summarize", requireAuth, summarizeLimiter, async (req, res) => {
  const { session_ids } = req.body;

  if (!session_ids || session_ids.length === 0) {
    return res.status(400).json({ error: "Missing session_ids." });
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
    return res.status(500).json({ error: "Error summarizing PDF." });
  }
});


// compare is admin-only (managing/comparing all documents is an elevated action)
app.post("/compare", requireAuth, requireRole("admin"), compareLimiter, async (req, res) => {
  const { session_ids } = req.body;

  if (!session_ids || session_ids.length < 2) {
    return res.status(400).json({ error: "Select at least 2 documents." });
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
    return res.status(500).json({ error: "Error comparing documents." });
  }
});


app.listen(PORT, () =>
  console.log(`Backend running on http://localhost:${PORT}`)
);