
import React, { useState, useEffect } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import { Document, Page, pdfjs } from "react-pdf";
import 'bootstrap/dist/css/bootstrap.min.css';
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

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:4000";

function App() {
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [authForm, setAuthForm] = useState({ email: "", password: "", isLogin: true });
  const [authError, setAuthError] = useState("");

  const [file, setFile] = useState(null);
  const [pdfs, setPdfs] = useState([]);
  const [selectedDocs, setSelectedDocs] = useState([]);
  const [chatHistory, setChatHistory] = useState([]);
  const [comparisonResult, setComparisonResult] = useState(null);
  const [question, setQuestion] = useState("");
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [darkMode, setDarkMode] = useState(false);

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
  const uploadPDF = async () => {
    if (!file) return;

    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await api.post("/upload", formData);
      const url = URL.createObjectURL(file);

      setPdfs(prev => [
        ...prev,
        { name: file.name, doc_id: res.data.doc_id, url }
      ]);

      setFile(null);
      alert("PDF uploaded!");
    } catch {
      alert("Upload failed.");
    }

    setUploading(false);
  };

  // ===============================
  // Toggle selection
  // ===============================
  const toggleDocSelection = (doc_id) => {
    setComparisonResult(null);
    setSelectedDocs(prev =>
      prev.includes(doc_id)
        ? prev.filter(id => id !== doc_id)
        : [...prev, doc_id]
    );
  };

  // ===============================
  // Ask
  // ===============================
  const askQuestion = async () => {
    if (!question.trim() || selectedDocs.length === 0) return;

    setChatHistory(prev => [...prev, { role: "user", text: question }]);
    setAsking(true);

    try {
      const res = await api.post("/ask", {
        question,
        doc_ids: selectedDocs
      });

      setChatHistory(prev => [
        ...prev,
        { role: "bot", text: res.data.answer }
      ]);
    } catch {
      setChatHistory(prev => [
        ...prev,
        { role: "bot", text: "Error getting answer." }
      ]);
    }

    setQuestion("");
    setAsking(false);
  };

  // ===============================
  // Summarize
  // ===============================
  const summarizePDF = async () => {
    if (selectedDocs.length === 0) return;

    setSummarizing(true);

    try {
      const res = await api.post("/summarize", {
        doc_ids: selectedDocs
      });

      setChatHistory(prev => [
        ...prev,
        { role: "bot", text: res.data.summary }
      ]);
    } catch {
      alert("Error summarizing.");
    }

    setSummarizing(false);
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

  return (
    <div className={themeClass} style={{ minHeight: "100vh" }}>
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
        </Container>
      </Navbar>

      <Container className="mt-4">

        {/* Upload */}
        <Card className="mb-4">
          <Card.Body>
            <Form>
              <Form.Control type="file" onChange={e => setFile(e.target.files[0])} />
              <Button
                className="mt-2"
                onClick={uploadPDF}
                disabled={!file || uploading}
              >
                {uploading ? <Spinner size="sm" animation="border" /> : "Upload"}
              </Button>
            </Form>
          </Card.Body>
        </Card>

        {/* Selection */}
        {pdfs.length > 0 && (
          <Card className="mb-4">
            <Card.Body>
              <h5>Select Documents</h5>
              {pdfs.map(pdf => (
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

        {/* Side-by-side View (ONLY when exactly 2 selected) */}
        {selectedPdfs.length === 2 && (
          <>
            <Row className="mb-4">
              {selectedPdfs.map(pdf => (
                <Col key={pdf.doc_id} md={6}>
                  <Card>
                    <Card.Body>
                      <h6>{pdf.name}</h6>
                      <Document file={pdf.url}>
                        <Page pageNumber={1} />
                      </Document>
                    </Card.Body>
                  </Card>
                </Col>
              ))}
            </Row>

            <Card className="mb-4">
              <Card.Body>
                <Button
                  variant="info"
                  onClick={compareDocuments}
                  disabled={comparing}
                >
                  {comparing ? <Spinner size="sm" animation="border" /> : "Generate Comparison"}
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
          <Card>
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

              <Form className="d-flex gap-2 mb-3">
                <Form.Control
                  type="text"
                  placeholder="Ask a question..."
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                />
                <Button
                  variant="success"
                  onClick={askQuestion}
                  disabled={asking}
                >
                  {asking ? <Spinner size="sm" animation="border" /> : "Ask"}
                </Button>
              </Form>

              <Button
                variant="warning"
                className="me-2"
                onClick={summarizePDF}
              >
                {summarizing ? <Spinner size="sm" animation="border" /> : "Summarize"}
              </Button>

              <Button
                variant="info"
                onClick={compareDocuments}
                disabled={selectedDocs.length < 2}
              >
                {comparing ? <Spinner size="sm" animation="border" /> : "Compare Selected"}
              </Button>

            </Card.Body>
          </Card>
        )}

      </Container>
    </div>
  );
}

export default App;
