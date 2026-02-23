import React, { useState, useEffect } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import { Document, Page, pdfjs } from "react-pdf";
import "bootstrap/dist/css/bootstrap.min.css";
import {
  Container,
  Button,
  Form,
  Card,
  Spinner,
  Navbar,
} from "react-bootstrap";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

const API_BASE = process.env.REACT_APP_API_URL || "";
const THEME_STORAGE_KEY = "pdf-qa-bot-theme";

function App() {
  // -------------------------------
  // Core state
  // -------------------------------
  const [file, setFile] = useState(null);
  const [pdfs, setPdfs] = useState([]); // { name, doc_id, url }
  const [selectedDocs, setSelectedDocs] = useState([]);
  const [question, setQuestion] = useState("");
  const [chatHistory, setChatHistory] = useState([]);
  const [comparisonResult, setComparisonResult] = useState(null);

  // -------------------------------
  // UI / status state
  // -------------------------------
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [comparing, setComparing] = useState(false);

  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);

  // -------------------------------
  // Theme persistence
  // -------------------------------
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return saved ? JSON.parse(saved) : false;
  });

  // -------------------------------
  // Session isolation (security fix)
  // -------------------------------
  const [sessionId, setSessionId] = useState("");

  useEffect(() => {
    setSessionId(
      crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).substring(2, 15)
    );
  }, []);

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(darkMode));
    document.body.classList.toggle("dark-mode", darkMode);
  }, [darkMode]);

  // -------------------------------
  // Upload PDF
  // -------------------------------
  const uploadPDF = async () => {
    if (!file) return;

    // Validate file type
    if (file.type !== "application/pdf") {
      alert("Please upload a valid PDF file.");
      return;
    }

    // Validate file size (10MB limit)
    const MAX_SIZE = 10 * 1024 * 1024; // 10MB
    if (file.size === 0) {
      alert("The selected PDF file is empty. Please choose a valid PDF.");
      return;
    }
    if (file.size > MAX_SIZE) {
      alert(`File size exceeds 10MB limit. Please upload a smaller PDF file.`);
      return;
    }

    setUploading(true);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("sessionId", sessionId);

    try {
      const res = await axios.post(`${API_BASE}/upload`, formData);
      const url = URL.createObjectURL(file);

      setPdfs((prev) => [
        ...prev,
        { name: file.name, doc_id: res.data?.doc_id, url },
      ]);

      setFile(null);
      alert("PDF uploaded successfully!");
    } catch (err) {
      const errorMsg = err.response?.data?.error || "Upload failed. The PDF may be corrupted or unreadable.";
      alert(errorMsg);
    }

    setUploading(false);
  };

  // -------------------------------
  // Toggle document selection
  // -------------------------------
  const toggleDocSelection = (docId) => {
    setComparisonResult(null);
    setSelectedDocs((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : [...prev, docId]
    );
  };

  // -------------------------------
  // Ask question
  // -------------------------------
  const askQuestion = async () => {
    if (!question.trim() || selectedDocs.length === 0) return;

    setChatHistory((prev) => [...prev, { role: "user", text: question }]);
    setQuestion("");
    setAsking(true);

    try {
      const res = await axios.post(`${API_BASE}/ask`, {
        question,
        doc_ids: selectedDocs,
        sessionId,
      });

      setChatHistory((prev) => [
        ...prev,
        { role: "bot", text: res.data.answer },
      ]);
    } catch {
      setChatHistory((prev) => [
        ...prev,
        { role: "bot", text: "Error getting answer." },
      ]);
    }

    setAsking(false);
  };

  // -------------------------------
  // Summarize PDFs
  // -------------------------------
  const summarizePDF = async () => {
    if (selectedDocs.length === 0) return;

    setSummarizing(true);

    try {
      const res = await axios.post(`${API_BASE}/summarize`, {
        doc_ids: selectedDocs,
        sessionId,
      });

      setChatHistory((prev) => [
        ...prev,
        { role: "bot", text: res.data.summary },
      ]);
    } catch {
      alert("Error summarizing.");
    }

    setSummarizing(false);
  };

  // -------------------------------
  // Compare PDFs
  // -------------------------------
  const compareDocuments = async () => {
    if (selectedDocs.length < 2) return;

    setComparing(true);

    try {
      const res = await axios.post(`${API_BASE}/compare`, {
        doc_ids: selectedDocs,
        sessionId,
      });

      setComparisonResult(res.data.comparison);
      setChatHistory((prev) => [
        ...prev,
        { role: "bot", text: res.data.comparison },
      ]);
    } catch {
      alert("Error comparing documents.");
    }

    setComparing(false);
  };

  // -------------------------------
  // UI helpers
  // -------------------------------
  const pageBg = darkMode ? "bg-dark text-light" : "bg-light text-dark";
  const cardClass = darkMode
    ? "text-white border-secondary shadow"
    : "bg-white text-dark border-0 shadow-sm";

  const inputClass = darkMode ? "text-white border-secondary" : "";

  // -------------------------------
  // Render
  // -------------------------------
  return (
    <div className={pageBg} style={{ minHeight: "100vh" }}>
      <Navbar bg={darkMode ? "dark" : "primary"} variant="dark">
        <Container className="d-flex justify-content-between">
          <Navbar.Brand>🤖 PDF Q&A Bot</Navbar.Brand>
          <Button
            variant="outline-light"
            onClick={() => setDarkMode(!darkMode)}
          >
            {darkMode ? "Light" : "Dark"}
          </Button>
        </Container>
      </Navbar>

      <Container className="mt-4">
        {/* Upload */}
        <Card className={`mb-4 ${cardClass}`}>
          <Card.Body>
            <Form>
              <Form.Control 
                type="file" 
                accept=".pdf,application/pdf"
                onChange={e => setFile(e.target.files[0])} 
              <Form.Control
                type="file"
                className={inputClass}
                onChange={(e) => setFile(e.target.files[0])}
              />
              <Button
                className="mt-2"
                onClick={uploadPDF}
                disabled={!file || uploading}
              >
                {uploading ? <Spinner size="sm" /> : "Upload"}
              </Button>
              <Form.Text className="text-muted d-block mt-2">
                Upload PDF files only (Max 10MB)
              </Form.Text>
            </Form>
          </Card.Body>
        </Card>

        {/* Document selection */}
        {pdfs.length > 0 && (
          <Card className={`mb-4 ${cardClass}`}>
            <Card.Body>
              <h5>Select Documents</h5>
              {pdfs.map((pdf) => (
                <Form.Check
                  key={pdf.doc_id}
                  type="checkbox"
                  label={pdf.name}
                  checked={selectedDocs.includes(pdf.doc_id)}
                  onChange={() => toggleDocSelection(pdf.doc_id)}
                />
              ))}
            </Card.Body>
          </Card>
        )}

        {/* Chat */}
        <Card className={cardClass}>
          <Card.Body>
            <div style={{ maxHeight: 300, overflowY: "auto", marginBottom: 16 }}>
              {chatHistory.map((msg, i) => (
                <div key={i} className="mb-2">
                  <strong>{msg.role === "user" ? "You" : "Bot"}:</strong>
                  <ReactMarkdown>{msg.text}</ReactMarkdown>
                </div>
              ))}
            </div>

            <Form
              className="d-flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                askQuestion();
              }}
            >
              <Form.Control
                type="text"
                placeholder="Ask a question..."
                value={question}
                className={inputClass}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={asking}
              />
              <Button disabled={asking || !question.trim()}>
                {asking ? <Spinner size="sm" /> : "Ask"}
              </Button>
            </Form>

            <div className="mt-3">
              <Button
                variant="warning"
                className="me-2"
                onClick={summarizePDF}
                disabled={summarizing}
              >
                {summarizing ? <Spinner size="sm" /> : "Summarize"}
              </Button>

              <Button
                variant="info"
                onClick={compareDocuments}
                disabled={selectedDocs.length < 2 || comparing}
              >
                {comparing ? <Spinner size="sm" /> : "Compare"}
              </Button>
            </div>
          </Card.Body>
        </Card>
      </Container>
    </div>
  );
}

export default App;