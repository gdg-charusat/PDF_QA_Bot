import React, { useState, useEffect } from "react";
import axios from "axios";
import { Container, Typography, Box, Button, TextField, Paper, Avatar, CircularProgress, AppBar, Toolbar, IconButton } from "@mui/material";
import UploadFileIcon from '@mui/icons-material/UploadFile';
import SendIcon from '@mui/icons-material/Send';

const CHAT_HISTORY_KEY = "pdf_bot_chat_history";
const SESSION_ID_KEY = "pdf_bot_session_id";

function App() {
  const [file, setFile] = useState(null);
  const [question, setQuestion] = useState("");
  const [chat, setChat] = useState(() => {
    try {
      const saved = localStorage.getItem(CHAT_HISTORY_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch (e) {
      console.error("Error parsing chat history from localStorage:", e);
      return [];
    }
  });
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [summarizing, setSummarizing] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  // Clear suggestions when switching PDFs
  useEffect(() => {
    setSuggestions([]);
  }, [selectedPdf]);
  const [sessionId, setSessionId] = useState(() => {
    return localStorage.getItem(SESSION_ID_KEY) || "";
  });

  // Initialize Session ID on mount if it doesn't exist
  useEffect(() => {
    if (!sessionId) {
      const newId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      setSessionId(newId);
      localStorage.setItem(SESSION_ID_KEY, newId);
    }
  }, [sessionId]);

  // Persist chat whenever it changes
  useEffect(() => {
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(chat));
  }, [chat]);

  const handleFileChange = (event) => {
    const selectedFile = event.target.files && event.target.files[0];
    if (!selectedFile) {
      setFile(null);
      return;
    }

    const name = selectedFile.name.toLowerCase();
    const isAllowed = name.endsWith(".pdf") || name.endsWith(".docx") || name.endsWith(".txt") || name.endsWith(".md");

    if (!isAllowed) {
      alert("Only PDF, DOCX, TXT, and MD files are supported.");
      event.target.value = "";
      setFile(null);
      return;
    }

    setFile(selectedFile);
  };

  const uploadPDF = async () => {
    if (!file || !sessionId) return;
    setUploading(true);
    setSuggestions([]); // Clear previous suggestions
    const formData = new FormData();
    formData.append("file", file);
    formData.append("sessionId", sessionId);

    try {
      await axios.post(`${API_BASE}/upload`, formData);
      const url = URL.createObjectURL(file);
      setPdfs(prev => [...prev, { name: file.name, url, chat: [] }]);
      setSelectedPdf(file.name);
      alert("PDF uploaded!");
      
      // Generate smart suggestions
      setLoadingSuggestions(true);
      try {
        const suggestionsRes = await axios.post(`${API_BASE}/generate-suggestions`);
        setSuggestions(suggestionsRes.data.suggestions || []);
      } catch (sugErr) {
        console.error("Failed to generate suggestions:", sugErr);
        setSuggestions([]);
      }
      setLoadingSuggestions(false);
    } catch (e) {
      console.error(e);
      alert("Upload failed. Ensure the server and RAG service are running.");
    }
    setUploading(false);
  };

  const askQuestion = async () => {
    if (!question.trim() || !sessionId) return;
    setAsking(true);
    const userMsg = { id: Date.now(), role: "user", text: question };
    setChat(prev => [...prev, userMsg]);

    try {
      const res = await axios.post("http://localhost:4000/ask", {
        question: question.trim(),
        session_ids: [sessionId]
      });
      setChat(prev => [...prev, {
        id: Date.now() + 1,
        role: "bot",
        text: res.data.answer,
        citations: res.data.citations || []
      }]);
    } catch (e) {
      setChat(prev => [...prev, { role: "bot", text: "Error getting answer. Please check if the document was uploaded for this session.", citations: [] }]);
    }
    setQuestion("");
    setAsking(false);
  };

  const clearHistory = async () => {
    if (window.confirm("Are you sure you want to clear your chat history?")) {
      try {
        await axios.post("http://localhost:4000/clear-history");
        setChat([]);
        localStorage.removeItem(CHAT_HISTORY_KEY);
      } catch (e) {
        alert("Failed to clear server-side history, but local history cleared.");
        setChat([]);
        localStorage.removeItem(CHAT_HISTORY_KEY);
      }
    }
  };

  return (
    <Container maxWidth="sm">
      <AppBar position="static" color="primary" sx={{ mb: 2 }}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>PDF Q&A Bot</Typography>
          <Button
            color="inherit"
            onClick={clearHistory}
            disabled={chat.length === 0}
            sx={{ mr: 2 }}
          >
            Clear History
          </Button>
          <Avatar sx={{ bgcolor: "white", color: "primary.main" }}>📄</Avatar>
        </Toolbar>
      </AppBar>

      <Paper elevation={3} sx={{ p: 3, mb: 2 }}>
        <Box display="flex" alignItems="center" gap={2}>
          <Button
            variant="contained"
            component="label"
            startIcon={<UploadFileIcon />}
            disabled={uploading}
          >
            Select PDF
            <input
              type="file"
              hidden
              accept=".pdf,.docx,.txt,.md"
              onChange={handleFileChange}
            />
          </Button>
          <Button variant="outlined" onClick={uploadPDF} disabled={!file || uploading}>
            {uploading ? <CircularProgress size={24} /> : "Upload"}
          </Button>
          {file && <Typography variant="body2" sx={{ maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{file.name}</Typography>}
        </Box>
      </Paper>

  return (
    <div className={themeClass} style={{ minHeight: "100vh", transition: "background 0.3s" }}>
      <Navbar bg={darkMode ? "dark" : "primary"} variant={darkMode ? "dark" : "light"} expand="lg" className="mb-4">
        <Container>
          <Navbar.Brand href="#">PDF Q&A Bot</Navbar.Brand>
          <Nav className="ml-auto">
            <ToggleButtonGroup type="radio" name="theme" value={darkMode ? 1 : 0} onChange={() => setDarkMode(!darkMode)}>
              <ToggleButton id="tbg-light" value={0} variant={darkMode ? "outline-light" : "outline-dark"}>Light</ToggleButton>
              <ToggleButton id="tbg-dark" value={1} variant={darkMode ? "outline-light" : "outline-dark"}>Dark</ToggleButton>
            </ToggleButtonGroup>
          </Nav>
        </Container>
      </Navbar>
      <Container>
        <Row className="justify-content-center mb-4">
          <Col md={8}>
            <Card className={darkMode ? "bg-secondary text-light" : "bg-white text-dark"}>
              <Card.Body>
                <Form>
                  <Form.Group controlId="formFile" className="mb-3">
                    <Form.Label>Upload PDF</Form.Label>
                    <Form.Control type="file" onChange={e => setFile(e.target.files[0])} />
                  </Form.Group>
                  <Button variant="primary" onClick={uploadPDF} disabled={!file || uploading}>
                    {uploading ? <Spinner animation="border" size="sm" /> : "Upload"}
                  </Button>
                  {file && <span className="ms-3">{file.name}</span>}
                </Form>
                {pdfs.length > 0 && (
                  <Dropdown className="mt-3">
                    <Dropdown.Toggle variant="info" id="dropdown-pdf">
                      {selectedPdf || "Select PDF"}
                    </Dropdown.Toggle>
                    <Dropdown.Menu>
                      {pdfs.map(pdf => (
                        <Dropdown.Item key={pdf.name} onClick={() => setSelectedPdf(pdf.name)}>{pdf.name}</Dropdown.Item>
                      ))}
                    </Dropdown.Menu>
                  </Dropdown>
                )}
              </Card.Body>
            </Card>
          </Col>
        </Row>
        {currentPdfUrl && (
          <Row className="justify-content-center mb-4">
            <Col md={8}>
              <Card className={darkMode ? "bg-secondary text-light" : "bg-white text-dark"}>
                <Card.Body>
                  <div style={{ textAlign: "center" }}>
                    <Document file={currentPdfUrl} onLoadSuccess={onDocumentLoadSuccess}>
                      <Page pageNumber={pageNumber} />
                    </Document>
                    <div className="d-flex justify-content-between align-items-center mt-2">
                      <Button variant="outline-info" size="sm" disabled={pageNumber <= 1} onClick={() => setPageNumber(pageNumber - 1)}>Prev</Button>
                      <span>Page {pageNumber} of {numPages}</span>
                      <Button variant="outline-info" size="sm" disabled={pageNumber >= numPages} onClick={() => setPageNumber(pageNumber + 1)}>Next</Button>
                    </div>
                  </div>
                </Card.Body>
              </Card>
            </Col>
          </Row>
        )}
        <Row className="justify-content-center">
          <Col md={8}>
            <Card className={darkMode ? "bg-secondary text-light" : "bg-white text-dark"}>
              <Card.Body style={{ minHeight: 300 }}>
                <h5>Chat</h5>
                <div style={{ maxHeight: 250, overflowY: "auto", marginBottom: 16 }}>
                  {currentChat.map((msg, i) => (
                    <div key={i} className={`d-flex ${msg.role === "user" ? "justify-content-end" : "justify-content-start"} mb-2`}>
                      <div className={`p-2 rounded ${msg.role === "user" ? "bg-primary text-light" : darkMode ? "bg-dark text-light" : "bg-light text-dark"}`} style={{ maxWidth: "80%" }}>
                        {msg.role === "bot" ? (
                          <ReactMarkdown>{msg.text}</ReactMarkdown>
                        ) : (
                          <span><strong>You:</strong> {msg.text}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {/* Smart Question Suggestions */}
                {loadingSuggestions && (
                  <div className="mb-2 text-center">
                    <Spinner animation="border" size="sm" className="me-2" />
                    <span>Generating suggestions...</span>
                  </div>
                )}
                {!loadingSuggestions && suggestions.length > 0 && (
                  <div className="mb-3">
                    <small className="text-muted">💡 Suggested questions:</small>
                    <div className="d-flex flex-wrap gap-2 mt-2">
                      {suggestions.map((q, idx) => (
                        <Button
                          key={idx}
                          variant="outline-info"
                          size="sm"
                          onClick={() => setQuestion(q)}
                          style={{ textAlign: 'left', whiteSpace: 'normal' }}
                        >
                          {q}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
                <Form className="d-flex gap-2 mb-2">
                  <Form.Control
                    type="text"
                    placeholder="Ask a question..."
                    value={question}
                    onChange={e => setQuestion(e.target.value)}
                    disabled={asking}
                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); askQuestion(); } }}
                  />
                  <Button variant="success" onClick={askQuestion} disabled={asking || !question.trim() || !selectedPdf}>
                    {asking ? <Spinner animation="border" size="sm" /> : "Ask"}
                  </Button>
                </Form>
                <Button variant="warning" className="me-2" onClick={summarizePDF} disabled={summarizing || !selectedPdf}>
                  {summarizing ? <Spinner animation="border" size="sm" /> : "Summarize PDF"}
                </Button>
                <Button variant="outline-secondary" className="me-2" onClick={() => exportChat("csv")} disabled={!selectedPdf}>Export CSV</Button>
                <Button variant="outline-secondary" onClick={() => exportChat("pdf")} disabled={!selectedPdf}>Export PDF</Button>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      </Container>
    </div>
      <Paper elevation={3} sx={{ p: 3, mb: 2, minHeight: 300, display: 'flex', flexDirection: 'column' }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="subtitle1">Conversation History</Typography>
        </Box>
        <Box sx={{ flexGrow: 1, maxHeight: 400, overflowY: "auto", mb: 2, border: '1px solid #eee', p: 1, borderRadius: 1 }}>
          {chat.length === 0 ? (
            <Typography variant="body2" color="text.secondary" align="center" sx={{ mt: 5 }}>
              No messages yet. Upload a PDF and ask a question!
            </Typography>
          ) : (
            chat.map((msg, i) => (
              <Box key={msg.id || `chat-msg-${i}`} display="flex" justifyContent={msg.role === "user" ? "flex-end" : "flex-start"} mb={1}>
                <Box
                  sx={{
                    bgcolor: msg.role === "user" ? "primary.light" : "grey.200",
                    color: msg.role === "user" ? "white" : "text.primary",
                    px: 2,
                    py: 1,
                    borderRadius: 2,
                    maxWidth: "80%"
                  }}
                >
                  <Typography variant="body2">
                    <b>{msg.role === "user" ? "You" : "Bot"}:</b> {msg.text}
                  </Typography>
                  {msg.role === "bot" && msg.citations && msg.citations.length > 0 && (
                    <Box mt={0.5} display="flex" flexWrap="wrap" gap={0.5}>
                      {msg.citations.map((c, j) => (
                        <Typography
                          key={`cit-${msg.id || i}-${j}`}
                          variant="caption"
                          sx={{ bgcolor: "grey.400", px: 1, py: 0.3, borderRadius: 1, display: "inline-block" }}
                        >
                          📄 {c.source} — p.{c.page}
                        </Typography>
                      ))}
                    </Box>
                  )}
                </Box>
              </Box>
            ))
          )}
        </Box>
        <Box display="flex" gap={1}>
          <TextField
            fullWidth
            variant="outlined"
            size="small"
            placeholder="Ask a question..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={asking}
            onKeyDown={e => { if (e.key === "Enter") askQuestion(); }}
          />
          <IconButton color="primary" onClick={askQuestion} disabled={asking || !question.trim()}>
            {asking ? <CircularProgress size={24} /> : <SendIcon />}
          </IconButton>
        </Box>
      </Paper>
    </Container>
  );
}

export default App;