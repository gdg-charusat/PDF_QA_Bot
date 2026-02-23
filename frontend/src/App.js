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
  Row,
  Col,
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
  // UI state
  // -------------------------------
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [comparing, setComparing] = useState(false);

  // -------------------------------
  // Theme persistence
  // -------------------------------
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return saved ? JSON.parse(saved) : false;
  });

  // -------------------------------
  // Session isolation
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

  // ===============================
  // localStorage Helper Functions
  // ===============================
  const isLocalStorageAvailable = () => {
    try {
      const test = "__localStorage_test__";
      localStorage.setItem(test, test);
      localStorage.removeItem(test);
      return true;
    } catch {
      return false;
    }
  };

  // Load from localStorage on mount
  useEffect(() => {
    if (!isLocalStorageAvailable()) return;

    const savedChatHistory = localStorage.getItem("chatHistory");
    const savedPdfs = localStorage.getItem("pdfs");

    if (savedChatHistory) {
      try {
        setChatHistory(JSON.parse(savedChatHistory));
      } catch (err) {
        console.error("Error loading chat history:", err);
      }
    }

    if (savedPdfs) {
      try {
        setPdfs(JSON.parse(savedPdfs));
      } catch (err) {
        console.error("Error loading PDFs:", err);
      }
    }
  }, []);

  // Save chatHistory to localStorage whenever it changes
  useEffect(() => {
    if (!isLocalStorageAvailable()) return;
    try {
      localStorage.setItem("chatHistory", JSON.stringify(chatHistory));
    } catch (err) {
      console.error("Error saving chat history:", err);
    }
  }, [chatHistory]);

  // Save pdfs to localStorage whenever it changes
  useEffect(() => {
    if (!isLocalStorageAvailable()) return;
    try {
      localStorage.setItem("pdfs", JSON.stringify(pdfs));
    } catch (err) {
      console.error("Error saving PDFs:", err);
    }
  }, [pdfs]);

  // Clear history function
  const clearHistory = () => {
    if (window.confirm("Are you sure you want to clear all chat history and uploads?")) {
      setChatHistory([]);
      setPdfs([]);
      setSelectedDocs([]);
      if (isLocalStorageAvailable()) {
        try {
          localStorage.removeItem("chatHistory");
          localStorage.removeItem("pdfs");
        } catch (err) {
          console.error("Error clearing localStorage:", err);
        }
      }
    }
  };

  // ===============================
  // Upload
  // ===============================
  const uploadDocument = async () => {
    if (!file) return;

    setUploading(true);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90_000);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("sessionId", sessionId);

      const res = await axios.post(`${API_BASE}/upload`, formData, {
        signal: controller.signal,
      });

      const url = URL.createObjectURL(file);
      const dotIndex = file.name.lastIndexOf(".");
      const ext =
        dotIndex !== -1 && dotIndex < file.name.length - 1
          ? file.name.substring(dotIndex + 1).toLowerCase()
          : "";

      setPdfs((prev) => [
        ...prev,
        { name: file.name, doc_id: res.data?.doc_id, url, ext },
      ]);

      setFile(null);
      alert("Document uploaded!");
    } catch (e) {
      if (e.name === "AbortError" || e.code === "ECONNABORTED") {
        alert("Upload timed out. Try a smaller document.");
      } else {
        alert("Upload failed.");
      }
    } finally {
      clearTimeout(timeoutId);
      setUploading(false);
    }
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
  // Ask question (with timeout)
  // -------------------------------
  const askQuestion = async () => {
    if (!question.trim() || selectedDocs.length === 0) return;
    if (question.length > 2000) {
      alert("Question too long (max 2000 characters)");
      return;
    }

    setAsking(true);
    setChatHistory((prev) => [...prev, { role: "user", text: question }]);
    setQuestion("");

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60_000);

    try {
      const res = await axios.post(
        `${API_BASE}/ask`,
        {
          question,
          sessionId,
          doc_ids: selectedDocs,
        },
        { signal: controller.signal }
      );

      setChatHistory((prev) => [
        ...prev,
        { role: "bot", text: res.data.answer, confidence: res.data.confidence_score },
      ]);
    } catch (e) {
      const msg =
        e.name === "AbortError" || e.code === "ECONNABORTED"
          ? "Request timed out."
          : "Error getting answer.";
      setChatHistory((prev) => [...prev, { role: "bot", text: msg }]);
    } finally {
      clearTimeout(timeoutId);
      setAsking(false);
    }
  };

  // -------------------------------
  // Summarize PDFs
  // -------------------------------
  const summarizePDF = async () => {
    if (selectedDocs.length === 0) return;

    setSummarizing(true);
    try {
      const res = await axios.post(`${API_BASE}/summarize`, {
        sessionId,
        doc_ids: selectedDocs,
      });
      setChatHistory((prev) => [
        ...prev,
        { role: "bot", text: res.data.summary },
      ]);
    } catch {
      alert("Error summarizing.");
    } finally {
      setSummarizing(false);
    }
  };

  // -------------------------------
  // Compare PDFs
  // -------------------------------
  const compareDocuments = async () => {
    if (selectedDocs.length < 2) return;

    setComparing(true);
    try {
      const res = await axios.post(`${API_BASE}/compare`, {
        sessionId,
        doc_ids: selectedDocs,
      });
      setComparisonResult(res.data.comparison);
      setChatHistory((prev) => [
        ...prev,
        { role: "bot", text: res.data.comparison },
      ]);
    } catch {
      alert("Error comparing documents.");
    } finally {
      setComparing(false);
    }
  };

  // -------------------------------
  // Helpers
  // -------------------------------
  const selectedPdfs = pdfs.filter((p) => selectedDocs.includes(p.doc_id));
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
        <Container className="d-flex justify-content-between align-items-center">
          <Navbar.Brand>PDF Q&A Bot</Navbar.Brand>
          <div className="d-flex gap-2">
            <Button variant="outline-light" onClick={() => setDarkMode(!darkMode)}>
              Toggle Theme
            </Button>
            <Button variant="outline-danger" onClick={clearHistory}>
              Clear History
            </Button>
          </div>
        </Container>
      </Navbar>

      <Container className="mt-4">
        {/* Upload */}
        <Card className={`mb-4 ${cardClass}`}>
          <Card.Body>
            <Form>
              <Form.Control
                type="file"
                className={inputClass}
                accept=".pdf,.docx,.txt,.md"
                onChange={(e) => setFile(e.target.files[0])}
              />
              <Button
                className="mt-2"
                onClick={uploadDocument}
                disabled={!file || uploading}
              >
                {uploading ? (
                  <Spinner size="sm" animation="border" />
                ) : (
                  "Upload Document"
                )}
              </Button>
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
        {/* Side-by-side comparison when 2 docs selected */}
        {selectedPdfs.length === 2 && (
          <>
            <Card className={`mb-4 ${cardClass}`}>
              <Card.Body>
                <Button
                  variant="info"
                  onClick={compareDocuments}
                  disabled={comparing}
                >
                  {comparing ? (
                    <Spinner size="sm" animation="border" />
                  ) : (
                    "Generate Comparison"
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
          </>
        )}

        {/* Chat Mode */}
        {selectedPdfs.length !== 2 && (
          <Card className={cardClass}>
            <Card.Body>
              <h5>Ask Across Selected Documents</h5>
              <div
                style={{ maxHeight: 300, overflowY: "auto", marginBottom: 16 }}
              >
                {chatHistory.map((msg, i) => (
                  <div key={i} className="mb-2">
                    <strong>{msg.role === "user" ? "You" : "Bot"}:</strong>
                    {msg.role === "bot" && msg.confidence !== undefined && (
                      <span
                        className="badge ms-2"
                        style={{
                          backgroundColor:
                            msg.confidence >= 70 ? "#28a745"
                              : msg.confidence >= 40 ? "#ffc107"
                                : "#dc3545",
                          color: msg.confidence >= 40 && msg.confidence < 70 ? "#856404" : "#fff",
                          fontSize: "0.7rem"
                        }}
                      >
                        Confidence: {msg.confidence}%
                      </span>
                    )}
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
                  className={inputClass}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      askQuestion();
                    }
                  }}
                />
                <Button
                  variant="success"
                  onClick={askQuestion}
                  disabled={asking}
                >
                  {asking ? <Spinner size="sm" animation="border" /> : "Ask"}
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
        )}
      </Container>
    </div>
  );
}

export default App;