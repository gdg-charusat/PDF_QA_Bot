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
    const formData = new FormData();
    formData.append("file", file);
    formData.append("sessionId", sessionId);

    try {
      await axios.post("http://localhost:4000/upload", formData);
      alert("PDF uploaded successfully!");
    } catch (e) {
      console.error(e);
      alert("Upload failed. Ensure the server and RAG service are running.");
    }
    setUploading(false);
  };

  const askQuestion = async () => {
    if (!question.trim() || !sessionId) return;
    setAsking(true);
    const userMsg = { role: "user", text: question };
    setChat(prev => [...prev, userMsg]);

    try {
      const res = await axios.post("http://localhost:4000/ask", {
        question: question.trim(),
        sessionId: sessionId
      });
      setChat(prev => [...prev, { role: "bot", text: res.data.answer }]);
    } catch (e) {
      setChat(prev => [...prev, { role: "bot", text: "Error getting answer. Please check if the document was uploaded for this session." }]);
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
              <Box key={i} display="flex" justifyContent={msg.role === "user" ? "flex-end" : "flex-start"} mb={1}>
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