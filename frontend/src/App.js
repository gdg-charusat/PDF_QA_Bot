import React, { useState, useEffect } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import "bootstrap/dist/css/bootstrap.min.css";
import {
  Container,
  Row,
  Col,
  Button,
  Form,
  Card,
  Spinner,
  Navbar
} from "react-bootstrap";

const API_BASE = process.env.REACT_APP_API_URL || "";
const THEME_STORAGE_KEY = "pdf-qa-bot-theme";

function App() {
  const [file, setFile] = useState(null);

  // Keep sessionId support (REQUIRED by reviewer)
  const [pdfs, setPdfs] = useState([]); // {name, url, session_id}
  const [selectedSessions, setSelectedSessions] = useState([]);
  const [chatHistory, setChatHistory] = useState([]);
  const [comparisonResult, setComparisonResult] = useState(null);
  const [question, setQuestion] = useState("");

  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [processingPdf, setProcessingPdf] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [comparing, setComparing] = useState(false);

  const [darkMode, setDarkMode] = useState(() => {
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    return savedTheme ? JSON.parse(savedTheme) : false;
  });

  // Theme persistence
  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(darkMode));
    document.body.classList.toggle("dark-mode", darkMode);
  }, [darkMode]);

  // Load saved data
  useEffect(() => {
    const savedChat = localStorage.getItem("chatHistory");
    const savedPdfs = localStorage.getItem("pdfs");

    if (savedChat) {
      try {
        setChatHistory(JSON.parse(savedChat));
      } catch {}
    }

    if (savedPdfs) {
      try {
        setPdfs(JSON.parse(savedPdfs));
      } catch {}
    }
  }, []);

  // Persist data
  useEffect(() => {
    localStorage.setItem("chatHistory", JSON.stringify(chatHistory));
  }, [chatHistory]);

  useEffect(() => {
    localStorage.setItem("pdfs", JSON.stringify(pdfs));
  }, [pdfs]);

  const clearHistory = () => {
    if (window.confirm("Clear all history and uploads?")) {
      setChatHistory([]);
      setPdfs([]);
      setSelectedSessions([]);
      localStorage.removeItem("chatHistory");
      localStorage.removeItem("pdfs");
    }
  };

  // Upload PDF (keeps session_id — CRITICAL)
  const uploadPDF = async () => {
    if (!file) return;
    setUploading(true);
    setProcessingPdf(true);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await axios.post(`${API_BASE}/upload`, formData);
      const url = URL.createObjectURL(file);

      setPdfs((prev) => [
        ...prev,
        {
          name: file.name,
          url,
          session_id: res.data.session_id, // REQUIRED: keep sessionId
        },
      ]);

      setFile(null);
      alert("PDF uploaded successfully!");
    } catch (e) {
      alert(e.response?.data?.error || "Upload failed.");
    }

    setUploading(false);
    setProcessingPdf(false);
  };

  const toggleDocSelection = (session_id) => {
    setComparisonResult(null);
    setSelectedSessions((prev) =>
      prev.includes(session_id)
        ? prev.filter((id) => id !== session_id)
        : [...prev, session_id]
    );
  };

  // Ask using session_ids (NOT doc_ids)
  const askQuestion = async () => {
    if (!question.trim() || selectedSessions.length === 0) return;

    setChatHistory((prev) => [...prev, { role: "user", text: question }]);
    const q = question;
    setQuestion("");
    setAsking(true);

    try {
      const res = await axios.post(`${API_BASE}/ask`, {
        question: q,
        session_ids: selectedSessions,
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

  const summarizePDF = async () => {
    if (selectedSessions.length === 0) return;
    setSummarizing(true);

    try {
      const res = await axios.post(`${API_BASE}/summarize`, {
        session_ids: selectedSessions,
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

  const compareDocuments = async () => {
    if (selectedSessions.length < 2) return;
    setComparing(true);

    try {
      const res = await axios.post(`${API_BASE}/compare`, {
        session_ids: selectedSessions,
      });
      setComparisonResult(res.data.comparison);
    } catch {
      alert("Error comparing documents.");
    }

    setComparing(false);
  };

  const selectedPdfs = pdfs.filter((p) =>
    selectedSessions.includes(p.session_id)
  );

  const pageBg = darkMode ? "bg-dark text-light" : "bg-light text-dark";
  const cardClass = darkMode
    ? "text-white border-secondary shadow"
    : "bg-white text-dark border-0 shadow-sm";

  return (
    <div className={pageBg} style={{ minHeight: "100vh" }}>
      <Navbar bg={darkMode ? "dark" : "primary"} variant="dark" className="mb-4">
        <Container className="d-flex justify-content-between">
          <Navbar.Brand>PDF Q&A Bot</Navbar.Brand>
          <div className="d-flex gap-2">
            <Button variant="danger" size="sm" onClick={clearHistory}>
              Clear History
            </Button>
            <Button
              variant="outline-light"
              onClick={() => setDarkMode(!darkMode)}
            >
              {darkMode ? "Light" : "Dark"}
            </Button>
          </div>
        </Container>
      </Navbar>

      <Container>
        <Card className={`mb-4 ${cardClass}`}>
          <Card.Body>
            <h5>Upload PDF</h5>
            <Form>
              <Form.Control
                type="file"
                onChange={(e) => setFile(e.target.files[0])}
              />
              <Button
                className="mt-2"
                onClick={uploadPDF}
                disabled={!file || uploading || processingPdf}
              >
                {uploading ? <Spinner size="sm" animation="border" /> : "Upload"}
              </Button>
            </Form>
          </Card.Body>
        </Card>

        {pdfs.length > 0 && (
          <Card className={`mb-4 ${cardClass}`}>
            <Card.Body>
              <h5>Select Documents</h5>
              {pdfs.map((pdf) => (
                <Form.Check
                  key={pdf.session_id}
                  type="checkbox"
                  label={pdf.name}
                  checked={selectedSessions.includes(pdf.session_id)}
                  onChange={() => toggleDocSelection(pdf.session_id)}
                />
              ))}
            </Card.Body>
          </Card>
        )}

        <Card className={cardClass}>
          <Card.Body>
            <h5>Ask Across Selected Documents</h5>

            <div style={{ maxHeight: 300, overflowY: "auto", marginBottom: 16 }}>
              {chatHistory.map((msg, i) => (
                <div key={i} className="mb-2">
                  <strong>{msg.role === "user" ? "You" : "Bot"}:</strong>
                  <ReactMarkdown>{msg.text}</ReactMarkdown>
                </div>
              ))}
            </div>

            <Form
              className="d-flex gap-2 mb-3"
              onSubmit={(e) => e.preventDefault()}
            >
              <Form.Control
                type="text"
                placeholder="Ask a question..."
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    askQuestion();
                  }
                }}
              />
              <Button variant="success" onClick={askQuestion} disabled={asking}>
                {asking ? <Spinner size="sm" animation="border" /> : "Ask"}
              </Button>
            </Form>

            <Button
              variant="warning"
              className="me-2"
              onClick={summarizePDF}
              disabled={summarizing}
            >
              {summarizing ? (
                <Spinner size="sm" animation="border" />
              ) : (
                "Summarize"
              )}
            </Button>

            <Button
              variant="info"
              onClick={compareDocuments}
              disabled={selectedSessions.length < 2}
            >
              {comparing ? (
                <Spinner size="sm" animation="border" />
              ) : (
                "Compare Selected"
              )}
            </Button>

            {comparisonResult && (
              <div className="mt-4">
                <h5>AI Comparison</h5>
                <ReactMarkdown>{comparisonResult}</ReactMarkdown>
              </div>
            )}
          </Card.Body>
        </Card>
      </Container>
    </div>
  );
}

export default App;