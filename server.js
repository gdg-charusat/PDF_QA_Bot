const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const path = require("path");
const fs = require("fs");

const app = express();
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

app.post("/upload", upload.single("file"), async (req, res) => {
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

    res.json({ doc_id: response.data.doc_id });
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
  }
});

app.post("/ask", async (req, res) => {
  const response = await axios.post("http://localhost:5000/ask", req.body);
  res.json(response.data);
});

app.post("/summarize", async (req, res) => {
  const response = await axios.post("http://localhost:5000/summarize", req.body);
  res.json(response.data);
});

app.post("/compare", async (req, res) => {
  try {
    const response = await axios.post("http://localhost:5000/compare", req.body);
    res.json({ comparison: response.data.comparison });
  } catch (err) {
    console.error(err.response?.data || err.message);
    res.status(500).json({ error: "Error comparing documents" });
  }
});

app.listen(4000, () => console.log("Backend running on http://localhost:4000"));