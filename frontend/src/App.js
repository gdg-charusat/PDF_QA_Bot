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

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:4000";

function App() {
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [authForm, setAuthForm] = useState({ email: "", password: "", isLogin: true });
  const [authError, setAuthError] = useState("");
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

  // Axios instance with interceptor for auth
  const api = axios.create({
    baseURL: API_BASE,
  });

  api.interceptors.request.use((config) => {
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  api.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response && error.response.status === 401) {
        handleLogout();
      }
      return Promise.reject(error);
    }
  );

  const handleAuth = async (e) => {
    e.preventDefault();
    setAuthError("");
    const endpoint = authForm.isLogin ? "/auth/login" : "/auth/register";
    try {
      const res = await axios.post(`${API_BASE}${endpoint}`, {
        email: authForm.email,
        password: authForm.password
      });

      if (authForm.isLogin) {
        const newToken = res.data.token;
        setToken(newToken);
        localStorage.setItem("token", newToken);
      } else {
        alert("Registered successfully! Please login.");
        setAuthForm({ ...authForm, isLogin: true });
      }
    } catch (err) {
      setAuthError(err.response?.data?.error || "Auth failed");
    }
  };

  const handleLogout = () => {
    setToken("");
    localStorage.removeItem("token");
    setPdfs([]);
    setChatHistory([]);
    setSelectedDocs([]);
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

      const res = await api.post("/upload", formData);
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

    try {
      const res = await api.post("/ask", {
        question,
        doc_ids: selectedDocs
      });
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
      const res = await api.post("/summarize", {
        doc_ids: selectedDocs
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

  // ===============================
  // Compare (Side-by-side OR Chat mode)
  // ===============================
  const compareDocuments = async () => {
    if (selectedDocs.length < 2) return;

    setComparing(true);

    try {
      const res = await api.post("/compare", {
        doc_ids: selectedDocs
      });

      // If exactly 2 → show structured side view
      if (selectedDocs.length === 2) {
        setComparisonResult(res.data.comparison);
      }
      // If more than 2 → push to chat mode
      else {
        setChatHistory(prev => [
          ...prev,
          { role: "user", text: "Compare selected documents." },
          { role: "bot", text: res.data.comparison }
        ]);
      }

    } catch {
      alert("Error comparing documents.");
    }

    setComparing(false);
  };

  const selectedPdfs = pdfs.filter(p =>
    selectedDocs.includes(p.doc_id)
  );

  const themeClass = darkMode ? "bg-dark text-light" : "bg-light text-dark";

  if (!token) {
    return (
      <div className={themeClass} style={{ minHeight: "100vh", display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Card style={{ width: '400px' }}>
          <Card.Body>
            <h3 className="text-center mb-4">{authForm.isLogin ? "Login" : "Register"}</h3>
            {authError && <div className="alert alert-danger">{authError}</div>}
            <Form onSubmit={handleAuth}>
              <Form.Group className="mb-3">
                <Form.Label>Email</Form.Label>
                <Form.Control
                  type="email"
                  value={authForm.email}
                  onChange={e => setAuthForm({ ...authForm, email: e.target.value })}
                  required
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Password</Form.Label>
                <Form.Control
                  type="password"
                  value={authForm.password}
                  onChange={e => setAuthForm({ ...authForm, password: e.target.value })}
                  required
                />
              </Form.Group>
              <Button type="submit" variant="primary" className="w-100">
                {authForm.isLogin ? "Login" : "Register"}
              </Button>
            </Form>
            <Button
              variant="link"
              className="w-100 mt-2"
              onClick={() => setAuthForm({ ...authForm, isLogin: !authForm.isLogin })}
            >
              {authForm.isLogin ? "Need an account? Register" : "Have an account? Login"}
            </Button>
          </Card.Body>
        </Card>
      </div>
    );
  }

  // Export chat
  const exportChat = (type) => {
    if (!selectedPdf) return;
    const chat = pdfs.find(pdf => pdf.name === selectedPdf)?.chat || [];
    if (type === "csv") {
      const csv = Papa.unparse(chat);
      const blob = new Blob([csv], { type: "text/csv" });
      saveAs(blob, `${selectedPdf}-chat.csv`);
    } else if (type === "pdf") {
      // Export chat as plain text (real PDF would require jsPDF/pdf-lib)
      const text = chat.map(msg => `${msg.role}: ${msg.text}`).join("\n\n");
      const blob = new Blob([text], { type: "text/plain" });
      saveAs(blob, `${selectedPdf}-chat.txt`);
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
        <Container>
          <Navbar.Brand>PDF Q&A Bot</Navbar.Brand>
          <div>
            <Button variant="outline-light" className="me-2" onClick={() => setDarkMode(!darkMode)}>
              Toggle Theme
            </Button>
            <Button variant="outline-danger" onClick={handleLogout}>
              Logout
            </Button>
          </div>
        <Container className="d-flex justify-content-between">
          <Navbar.Brand>🤖 PDF Q&A Bot</Navbar.Brand>
          <Button variant="outline-light" onClick={() => setDarkMode(!darkMode)}>
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
