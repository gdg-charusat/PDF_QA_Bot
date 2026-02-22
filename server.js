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

// Storage for uploaded PDFs with file size limit (10MB)
const upload = multer({ 
  dest: "uploads/",
  limits: { fileSize: 10 * 1024 * 1024 } // 10MB limit
});

// Route: Upload PDF
app.post("/upload", uploadLimiter, upload.single("file"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded. Use form field name 'file'." });
    }

    // Validate file type
    if (req.file.mimetype !== "application/pdf") {
      fs.unlinkSync(req.file.path);
      return res.status(400).json({ error: "Invalid file type. Only PDF files are allowed." });
    }

    // Validate file size (not empty)
    if (req.file.size === 0) {
      fs.unlinkSync(req.file.path);
      return res.status(400).json({ error: "Uploaded file is empty. Please upload a valid PDF." });
    }

    // Validate PDF header
    const buffer = fs.readFileSync(req.file.path);
    const isPDF = buffer.toString('utf8', 0, 4) === '%PDF';
    if (!isPDF) {
      fs.unlinkSync(req.file.path);
      return res.status(400).json({ error: "File is corrupted or not a valid PDF." });
    }

    const filePath = path.join(__dirname, req.file.path);

    // Send PDF to Python service
    const response = await axios.post("http://localhost:5000/process-pdf", {
      filePath: filePath,
    });

    res.json({ message: "PDF uploaded & processed successfully!", doc_id: response.data.doc_id });
  } catch (err) {
    // Clean up file if it exists
    if (req.file?.path && fs.existsSync(req.file.path)) {
      fs.unlinkSync(req.file.path);
    }
    
    if (err.code === 'LIMIT_FILE_SIZE') {
      return res.status(400).json({ error: "File too large. Maximum size is 10MB." });
    }
    
    const details = err.response?.data?.detail || err.response?.data?.error || err.message;
    console.error("Upload processing failed:", details);
    return res.status(500).json({ error: "PDF processing failed", details });
  }
});

// Route: Ask Question
app.post("/ask", askLimiter, async (req, res) => {
  const { question } = req.body;
  try {
    const response = await axios.post("http://localhost:5000/ask", {
      question,
    });

    res.json({ answer: response.data.answer });
  } catch (err) {
    console.error(err.message);
    res.status(500).json({ error: "Error answering question" });
  }
});

app.post("/summarize", summarizeLimiter, async (req, res) => {
  try {
    const response = await axios.post("http://localhost:5000/summarize", req.body || {});
    res.json({ summary: response.data.summary });
  } catch (err) {
    const details = err.response?.data || err.message;
    console.error("Summarization failed:", details);
    res.status(500).json({ error: "Error summarizing PDF", details });
  }
});

app.listen(4000, () => console.log("Backend running on http://localhost:4000"));