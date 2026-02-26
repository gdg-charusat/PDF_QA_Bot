import React, { useState } from "react";
import { Card, Form, Button, Spinner } from "react-bootstrap";
import ReactMarkdown from "react-markdown";
import { askQuestion, summarizeDocuments } from "../services/api";

/**
 * ChatInterface component
 * Handles asking questions and summarizing documents
 */
const ChatInterface = ({
  chatHistory,
  selectedDocIds,
  selectedDocCount,
  sessionId,
  cardClass,
  inputClass,
  onChatUpdate,
}) => {
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [summarizing, setSummarizing] = useState(false);

  const handleAskQuestion = async () => {
    if (!question.trim() || selectedDocCount === 0) {
      alert("Please enter a question and select at least one document");
      return;
    }

    setAsking(true);
    
    // Optimistically add user message
    onChatUpdate({ role: "user", text: question });
    const questionText = question;
    setQuestion("");

    try {
      const response = await askQuestion(
        questionText,
        sessionId,
        selectedDocIds
      );
      onChatUpdate({
        role: "bot",
        text: response.text,
        confidence: response.confidence,
      });
    } catch (error) {
      onChatUpdate({
        role: "bot",
        text: `Error: ${error.message}`,
      });
    } finally {
      setAsking(false);
    }
  };

  const handleSummarize = async () => {
    setSummarizing(true);
    try {
      const response = await summarizeDocuments(sessionId, selectedDocIds);
      onChatUpdate({
        role: "bot",
        text: response.text,
      });
    } catch (error) {
      onChatUpdate({
        role: "bot",
        text: `Error: ${error.message}`,
      });
    } finally {
      setSummarizing(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAskQuestion();
    }
  };

  return (
    <Card className={cardClass}>
      <Card.Body>
        <Card.Title>Ask Across Selected Documents</Card.Title>

        {/* Chat History */}
        <div
          style={{
            maxHeight: 300,
            overflowY: "auto",
            marginBottom: 16,
            borderBottom: "1px solid #ddd",
            paddingBottom: 16,
          }}
        >
          {chatHistory && chatHistory.length === 0 ? (
            <p className="text-muted">No messages yet. Ask a question to start.</p>
          ) : (
            chatHistory.map((msg, i) => (
              <div key={i} className="mb-3">
                <div className="d-flex justify-content-between align-items-start">
                  <strong>{msg.role === "user" ? "You" : "Bot"}:</strong>
                  {msg.role === "bot" && msg.confidence !== undefined && (
                    <span
                      className="badge"
                      style={{
                        backgroundColor:
                          msg.confidence >= 70
                            ? "#28a745"
                            : msg.confidence >= 40
                            ? "#ffc107"
                            : "#dc3545",
                        color:
                          msg.confidence >= 40 && msg.confidence < 70
                            ? "#856404"
                            : "#fff",
                        fontSize: "0.7rem",
                      }}
                    >
                      Confidence: {msg.confidence}%
                    </span>
                  )}
                </div>
                <ReactMarkdown>{msg.text}</ReactMarkdown>
              </div>
            ))
          )}
        </div>

        {/* Question Input */}
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
            onKeyDown={handleKeyDown}
            disabled={asking || selectedDocCount === 0}
          />
          <Button
            variant="success"
            onClick={handleAskQuestion}
            disabled={asking || !question.trim() || selectedDocCount === 0}
          >
            {asking ? <Spinner size="sm" animation="border" /> : "Ask"}
          </Button>
        </Form>

        {/* Action Buttons */}
        <div className="mt-3 d-flex gap-2 flex-wrap">
          <Button
            variant="warning"
            onClick={handleSummarize}
            disabled={summarizing || selectedDocCount === 0}
            size="sm"
          >
            {summarizing ? (
              <>
                <Spinner size="sm" animation="border" className="me-2" />
                Summarizing...
              </>
            ) : (
              "Summarize"
            )}
          </Button>
        </div>
      </Card.Body>
    </Card>
  );
};

export default ChatInterface;
