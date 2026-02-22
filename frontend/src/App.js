
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

const API_BASE = process.env.REACT_APP_API_URL || "";

function App() {
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

  // ===============================
  // Upload
  // ===============================
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

    try {
      const res = await axios.post(`${API_BASE}/upload`, formData);
      const url = URL.createObjectURL(file);

      setPdfs(prev => [
        ...prev,
        { name: file.name, doc_id: res.data.doc_id, url }
      ]);

      setFile(null);
      alert("PDF uploaded successfully!");
    } catch (err) {
      const errorMsg = err.response?.data?.error || "Upload failed. The PDF may be corrupted or unreadable.";
      alert(errorMsg);
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
      const res = await axios.post(`${API_BASE}/ask`, {
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
      const res = await axios.post(`${API_BASE}/summarize`, {
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
      const res = await axios.post(`${API_BASE}/compare`, {
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

  const toggleTheme = () => {
    setDarkMode(!darkMode);
  };

  return (
    <div className={themeClass} style={{ minHeight: "100vh" }}>
      <Navbar bg={darkMode ? "dark" : "primary"} variant="dark">
        <Container>
          <Navbar.Brand>PDF Q&A Bot</Navbar.Brand>
          <Button variant="outline-light" onClick={() => setDarkMode(!darkMode)}>
            Toggle Theme
          </Button>
        </Container>
      </Navbar>

      <Container className="mt-4">

        {/* Upload */}
        <Card className="mb-4">
          <Card.Body>
            <Form>
              <Form.Control 
                type="file" 
                accept=".pdf,application/pdf"
                onChange={e => setFile(e.target.files[0])} 
              />
              <Button
                className="mt-2"
                onClick={uploadPDF}
                disabled={!file || uploading}
              >
                {uploading ? <Spinner size="sm" animation="border" /> : "Upload"}
              </Button>
              <Form.Text className="text-muted d-block mt-2">
                Upload PDF files only (Max 10MB)
              </Form.Text>
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