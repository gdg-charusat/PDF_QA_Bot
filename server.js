const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const path = require("path");
require("dotenv").config();

const authRoutes = require("./routes/auth");
const { authenticate, authorize } = require("./middleware/auth");

const app = express();
app.use(cors());
app.use(express.json());

// Auth Routes
app.use("/auth", authRoutes);

const upload = multer({ dest: "uploads/" });

// Apply authentication to all PDF processing and QA routes
// For now, allowing both 'user' and 'admin' for all, but can be customized per-route
app.use(["/upload", "/ask", "/summarize", "/compare"], authenticate);

app.post("/upload", authorize(["admin", "user"]), upload.single("file"), async (req, res) => {
  try {
    const filePath = path.join(__dirname, req.file.path);
    const response = await axios.post("http://localhost:5000/process-pdf", {
      filePath,
    });

    res.json({ doc_id: response.data.doc_id });
  } catch (err) {
    console.error("Upload error:", err.message);
    res.status(500).json({ error: "Upload failed" });
  }
});

app.post("/ask", authorize(["admin", "user"]), async (req, res) => {
  try {
    const response = await axios.post("http://localhost:5000/ask", req.body);
    res.json(response.data);
  } catch (err) {
    console.error("Ask error:", err.message);
    res.status(500).json({ error: "Error getting answer" });
  }
});

app.post("/summarize", authorize(["admin", "user"]), async (req, res) => {
  try {
    const response = await axios.post("http://localhost:5000/summarize", req.body);
    res.json(response.data);
  } catch (err) {
    console.error("Summarize error:", err.message);
    res.status(500).json({ error: "Error summarizing" });
  }
});

app.post("/compare", authorize(["admin", "user"]), async (req, res) => {
  try {
    const response = await axios.post("http://localhost:5000/compare", req.body);
    res.json({ comparison: response.data.comparison });
  } catch (err) {
    console.error("Compare error:", err.response?.data || err.message);
    res.status(500).json({ error: "Error comparing documents" });
  }
});

app.listen(4000, () => console.log("Backend running on http://localhost:4000"));
