const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const rateLimit = require("express-rate-limit");

const app = express();
app.use(cors());
app.use(express.json());

// Rate limiting middleware
const uploadLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 5, // Limit each IP to 5 upload requests per windowMs
  message: "Too many PDF uploads from this IP, please try again after 15 minutes",
  standardHeaders: true,
  legacyHeaders: false,
});

const askLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 30, // Limit each IP to 30 questions per windowMs
  message: "Too many questions asked, please try again after 15 minutes",
  standardHeaders: true,
  legacyHeaders: false,
});

const summarizeLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 10, // Limit each IP to 10 summarizations per windowMs
  message: "Too many summarization requests, please try again after 15 minutes",
  standardHeaders: true,
  legacyHeaders: false,
});

// Storage for uploaded PDFs
const upload = multer({ dest: "uploads/" });

// Route: Upload PDF
app.post("/upload", uploadLimiter, upload.single("file"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded. Use form field name 'file'." });
    }

    const filePath = path.join(__dirname, req.file.path);

    // Send PDF to Python service
    const response = await axios.post("http://localhost:5000/process-pdf", {
      filePath: filePath,
      filename: req.file.originalname,
    });

    if (response.data.error) {
      throw new Error(response.data.error);
    }

    res.json({ message: "PDF uploaded & processed successfully!" });
  } catch (err) {
    const details = err.response?.data || err.message;
    console.error("Upload processing failed:", details);
    res.status(500).json({ error: "PDF processing failed", details });
  }
});

// Route: Ask Question
app.post("/ask", askLimiter, async (req, res) => {
  const { question } = req.body;
  try {
    const response = await axios.post("http://localhost:5000/ask", {
      question,
    });

    if (response.data.error) {
      throw new Error(response.data.error);
    }

    res.json({ answer: response.data.answer });
  } catch (err) {
    const details = err.response?.data || err.message;
    console.error("Error answering question:", details);
    res.status(500).json({ error: "Error answering question", details });
  }
});

app.post("/summarize", summarizeLimiter, async (req, res) => {
  try {
    const response = await axios.post("http://localhost:5000/summarize", req.body || {});

    if (response.data.error) {
      throw new Error(response.data.error);
    }

    res.json({ summary: response.data.summary });
  } catch (err) {
    const details = err.response?.data || err.message;
    console.error("Summarization failed:", details);
    res.status(500).json({ error: "Error summarizing PDF", details });
  }
});

app.listen(4000, () => console.log("Backend running on http://localhost:4000"));
