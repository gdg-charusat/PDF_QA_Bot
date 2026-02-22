import React, { useState, useEffect } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import { Document, Page, pdfjs } from "react-pdf";
import Papa from "papaparse";
import "bootstrap/dist/css/bootstrap.min.css";
import {
  Container,
  Row,
  Col,
  Button,
  Form,
  Card,
  Spinner,
  Navbar,
  Dropdown,
} from "react-bootstrap";

import "./App.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

const API_BASE = process.env.REACT_APP_API_URL || "";
const THEME_STORAGE_KEY = "pdf-qa-bot-theme";

function App() {
  // File + PDF states
  const [file, setFile] = useState(null);
  const [pdfs, setPdfs] = useState([]); // {name, doc_id, url, chat, processed}
  const [selectedPdf, setSelectedPdf] = useState(null);
  const [selectedDocs, setSelectedDocs] = useState([]);
  const [chatHistory, setChatHistory] = useState([]);
  const [comparisonResult, setComparisonResult] = useState(null);

  // UI states
  const [question, setQuestion] = useState("");
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [processingPdf, setProcessingPdf] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [comparing, setComparing] = useState(false);

  // Theme
  const [darkMode, setDarkMode] = useState(() => {
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    return savedTheme ? JSON.parse(savedTheme) : false;
  });

  // PDF Viewer
  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(darkMode));
    document.body.classList.toggle("dark-mode", darkMode);
  }, [darkMode]);

  // Upload PDF
  const uploadPDF = async () => {
    if (!file) return;
    setUploading(true);
    setProcessingPdf(true);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await axios.post(`${API_BASE}/upload`, formData);
      const url = URL.createObjectURL(file);

      const newPdf = {
        name: file.name,
        doc_id: res.data?.doc_id || file.name,
        url,
        chat: [],
        processed: true,
      };

      setPdfs((prev) => [...prev, newPdf]);
      setSelectedPdf(file.name);
      setFile(null);
      alert("PDF uploaded and processed successfully!");
    } catch (e) {
      const message = e.response?.data?.error || "Upload failed.";
      alert(message);
    } finally {
      setUploading(false);
      setProcessingPdf(false);
    }
  };

  // Toggle multi-doc selection
  const toggleDocSelection = (doc_id) => {
    setComparisonResult(null);
    setSelectedDocs((prev) =>
      prev.includes(doc_id)
        ? prev.filter((id) => id !== doc_id)
        : [...prev, doc_id]
    );
  };

  // Ask Question (Single PDF)
  const askQuestionSingle = async () => {
    if (!question.trim() || !selectedPdf) return;

    const pdfData = pdfs.find((pdf) => pdf.name === selectedPdf);
    if (!pdfData || !pdfData.processed) return;

    const updatedChat = [...pdfData.chat, { role: "user", text: question }];
    setPdfs((prev) =>
      prev.map((pdf) =>
        pdf.name === selectedPdf ? { ...pdf, chat: updatedChat } : pdf
      )
    );

    setAsking(true);

    try {
      const res = await axios.post(`${API_BASE}/ask`, {
        question,
        doc_ids: [pdfData.doc_id],
      });

      setPdfs((prev) =>
        prev.map((pdf) =>
          pdf.name === selectedPdf
            ? {
                ...pdf,
                chat: [...updatedChat, { role: "bot", text: res.data.answer }],
              }
            : pdf
        )
      );
    } catch {
      setPdfs((prev) =>
        prev.map((pdf) =>
          pdf.name === selectedPdf
            ? {
                ...pdf,
                chat: [...updatedChat, { role: "bot", text: "Error getting answer." }],
              }
            : pdf
        )
      );
    }

    setQuestion("");
    setAsking(false);
  };

  // Ask Question (Multi-doc)
  const askQuestionMulti = async () => {
    if (!question.trim() || selectedDocs.length === 0) return;

    setChatHistory((prev) => [...prev, { role: "user", text: question }]);
    setAsking(true);

    try {
      const res = await axios.post(`${API_BASE}/ask`, {
        question,
        doc_ids: selectedDocs,
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

    setQuestion("");
    setAsking(false);
  };

  // Summarize
  const summarizePDF = async () => {
    if (!selectedPdf && selectedDocs.length === 0) return;

    setSummarizing(true);

    try {
      let doc_ids = [];

      if (selectedDocs.length > 0) {
        doc_ids = selectedDocs;
      } else {
        const pdfData = pdfs.find((pdf) => pdf.name === selectedPdf);
        doc_ids = [pdfData.doc_id];
      }

      const res = await axios.post(`${API_BASE}/summarize`, { doc_ids });

      if (selectedDocs.length > 0) {
        setChatHistory((prev) => [
          ...prev,
          { role: "bot", text: res.data.summary },
        ]);
      } else {
        setPdfs((prev) =>
          prev.map((pdf) =>
            pdf.name === selectedPdf
              ? {
                  ...pdf,
                  chat: [...pdf.chat, { role: "bot", text: res.data.summary }],
                }
              : pdf
          )
        );
      }
    } catch {
      alert("Error summarizing.");
    }

    setSummarizing(false);
  };

  // Compare Documents
  const compareDocuments = async () => {
    if (selectedDocs.length < 2) return;
    setComparing(true);

    try {
      const res = await axios.post(`${API_BASE}/compare`, {
        doc_ids: selectedDocs,
      });
      setComparisonResult(res.data.comparison);
    } catch {
      alert("Comparison failed.");
    }

    setComparing(false);
  };

  // Export Chat CSV
  const exportChat = () => {
    if (!selectedPdf) return;
    const chat = pdfs.find((pdf) => pdf.name === selectedPdf)?.chat || [];
    if (chat.length === 0) return;

    const csv = Papa.unparse(chat);
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedPdf}_chat.csv`;
    a.click();
  };

  // Helpers
  const selectedPdfs = pdfs.filter((p) =>
    selectedDocs.includes(p.doc_id)
  );
  const currentChat =
    pdfs.find((pdf) => pdf.name === selectedPdf)?.chat || [];
  const currentPdfUrl =
    pdfs.find((pdf) => pdf.name === selectedPdf)?.url || null;
  const isPdfProcessed =
    pdfs.find((pdf) => pdf.name === selectedPdf)?.processed || false;
  const canAskQuestions =
    selectedPdf && isPdfProcessed && !processingPdf;
  const themeClass = darkMode ? "bg-dark text-light" : "bg-light text-dark";

  return (
    <div
      className={`${themeClass} app-container`}
      style={{ minHeight: "100vh", transition: "all 0.3s ease" }}
    >
      <Navbar
        bg={darkMode ? "dark" : "primary"}
        variant={darkMode ? "dark" : "light"}
        className="mb-4 shadow-sm"
      >
        <Container>
          <Navbar.Brand>📄 PDF Q&A Bot</Navbar.Brand>
          <Button variant="outline-light" onClick={() => setDarkMode(!darkMode)}>
            {darkMode ? "☀️ Light" : "🌙 Dark"} Mode
          </Button>
        </Container>
      </Navbar>

      <Container className="mt-4">
        {/* Upload Section */}
        <Card className="mb-4">
          <Card.Body>
            <h5>📤 Upload PDF</h5>
            <Form>
              <Form.Control
                type="file"
                onChange={(e) => setFile(e.target.files[0])}
                className={darkMode ? "bg-dark text-light border-secondary" : ""}
              />
              <Button
                className="mt-2"
                onClick={uploadPDF}
                disabled={!file || uploading || processingPdf}
              >
                {uploading || processingPdf ? (
                  <Spinner size="sm" animation="border" />
                ) : (
                  "Upload"
                )}
              </Button>
            </Form>

            {pdfs.length > 0 && (
              <Dropdown className="mt-3">
                <Dropdown.Toggle
                  variant={darkMode ? "outline-light" : "info"}
                >
                  📚 {selectedPdf || "Select PDF"}
                </Dropdown.Toggle>
                <Dropdown.Menu className={darkMode ? "bg-dark" : ""}>
                  {pdfs.map((pdf) => (
                    <Dropdown.Item
                      key={pdf.name}
                      onClick={() => setSelectedPdf(pdf.name)}
                      className={darkMode ? "text-light" : ""}
                    >
                      {pdf.name} {pdf.processed ? "✅" : "⏳"}
                    </Dropdown.Item>
                  ))}
                </Dropdown.Menu>
              </Dropdown>
            )}
          </Card.Body>
        </Card>

        {/* Chat Section */}
        <Card>
          <Card.Body>
            <h5>💬 Chat with PDF</h5>

            <div style={{ maxHeight: 300, overflowY: "auto" }}>
              {currentChat.map((msg, i) => (
                <div key={i} className="mb-2">
                  <strong>{msg.role === "user" ? "You" : "Bot"}:</strong>
                  <ReactMarkdown>{msg.text}</ReactMarkdown>
                </div>
              ))}
            </div>

            <Form className="d-flex gap-2 mt-3">
              <Form.Control
                type="text"
                placeholder="Ask a question..."
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={!canAskQuestions}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    askQuestionSingle();
                  }
                }}
              />
              <Button
                variant="success"
                onClick={askQuestionSingle}
                disabled={!canAskQuestions || !question.trim()}
              >
                {asking ? <Spinner size="sm" /> : "Ask"}
              </Button>
            </Form>

            <div className="mt-3 d-flex gap-2">
              <Button
                variant="warning"
                onClick={summarizePDF}
                disabled={summarizing || !canAskQuestions}
              >
                {summarizing ? <Spinner size="sm" /> : "📝 Summarize"}
              </Button>

              <Button
                variant="secondary"
                onClick={exportChat}
                disabled={currentChat.length === 0}
              >
                📊 Export CSV
              </Button>
            </div>
          </Card.Body>
        </Card>
      </Container>
    </div>
  );
}

export default App;