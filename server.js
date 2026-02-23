const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const path = require("path");
const crypto = require("crypto");

const app = express();
app.use(cors({ origin: true, credentials: true }));
app.use(express.json());

const upload = multer({ dest: "uploads/" });

// ===============================
// SESSION MANAGEMENT
// ===============================
// Generate a unique session ID per client connection.
// The session ID is sent as a cookie and forwarded to the RAG service
// to ensure each user only accesses their own documents.
const SESSION_COOKIE = "pdf_qa_session_id";

function getOrCreateSessionId(req, res) {
  let sessionId = req.cookies && req.cookies[SESSION_COOKIE];
  if (!sessionId) {
    // Also check the header in case cookies are not available
    sessionId = req.headers["x-session-id"];
  }
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    res.cookie(SESSION_COOKIE, sessionId, {
      httpOnly: true,
      sameSite: "lax",
      maxAge: 24 * 60 * 60 * 1000, // 24 hours
    });
  }
  return sessionId;
}

// Cookie parser middleware (lightweight, no dependency needed)
app.use((req, res, next) => {
  const cookieHeader = req.headers.cookie;
  req.cookies = {};
  if (cookieHeader) {
    cookieHeader.split(";").forEach((cookie) => {
      const [name, ...rest] = cookie.trim().split("=");
      req.cookies[name.trim()] = decodeURIComponent(rest.join("="));
    });
  }
  next();
});

app.post("/upload", upload.single("file"), async (req, res) => {
  try {
    const sessionId = getOrCreateSessionId(req, res);
    const filePath = path.join(__dirname, req.file.path);
    const response = await axios.post("http://localhost:5000/process-pdf", {
      filePath,
      session_id: sessionId,
    });

    res.json({ doc_id: response.data.doc_id });
  } catch (err) {
    res.status(500).json({ error: "Upload failed" });
  }
});

app.post("/ask", async (req, res) => {
  try {
    const sessionId = getOrCreateSessionId(req, res);
    const response = await axios.post("http://localhost:5000/ask", {
      ...req.body,
      session_id: sessionId,
    });
    res.json(response.data);
  } catch (err) {
    res.status(500).json({ error: "Error getting answer" });
  }
});

app.post("/summarize", async (req, res) => {
  try {
    const sessionId = getOrCreateSessionId(req, res);
    const response = await axios.post("http://localhost:5000/summarize", {
      ...req.body,
      session_id: sessionId,
    });
    res.json(response.data);
  } catch (err) {
    res.status(500).json({ error: "Error summarizing" });
  }
});

app.post("/compare", async (req, res) => {
  try {
    const sessionId = getOrCreateSessionId(req, res);
    const response = await axios.post("http://localhost:5000/compare", {
      ...req.body,
      session_id: sessionId,
    });
    res.json({ comparison: response.data.comparison });
  } catch (err) {
    console.error(err.response?.data || err.message);
    res.status(500).json({ error: "Error comparing documents" });
  }
});

app.post("/cleanup-session", async (req, res) => {
  try {
    const sessionId = getOrCreateSessionId(req, res);
    const response = await axios.post("http://localhost:5000/cleanup-session", {
      session_id: sessionId,
    });
    res.json(response.data);
  } catch (err) {
    res.status(500).json({ error: "Error cleaning up session" });
  }
});

app.listen(4000, () => console.log("Backend running on http://localhost:4000"));