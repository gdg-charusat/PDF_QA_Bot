import React, { useState } from "react";
import { Card, Form, Button, Spinner } from "react-bootstrap";
import ReactMarkdown from "react-markdown";
import { askQuestion, askQuestionStream, summarizeDocuments } from "../services/api";

/**
 * ChatInterface component
 * Handles asking questions and summarizing documents
 * Issue #118: Implements real-time token streaming for improved UX
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
  const [useStreaming] = useState(true); // Enable streaming by default

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
      // Use streaming for real-time feedback (Issue #118)
      if (useStreaming) {
        let fullAnswer = "";
        let citations = [];

        await askQuestionStream(
          questionText,
          selectedDocIds.length > 0 ? selectedDocIds : [],
          (token) => {
            // Handle final post-processed answer
            if (typeof token === "object" && token.type === "final_answer") {
              fullAnswer = token.answer;
              // Replace streamed text with cleaned answer (context leakage stripped)
              onChatUpdate({
                role: "bot",
                text: fullAnswer,
                isStreaming: false,
                citations: citations,
                isCleaned: true,
              });
            } else if (typeof token === "string") {
              // Accumulate individual tokens for real-time display
              fullAnswer += token;
              // Update chat incrementally as tokens arrive (streaming effect)
              onChatUpdate({
                role: "bot",
                text: fullAnswer,
                isStreaming: true,
                citations: citations,
              });
            }
          },
          (newCitations) => {
            // Update citations when they arrive
            citations = newCitations;
          }
        );

        // Finalize message (not streaming anymore)
        onChatUpdate({
          role: "bot",
          text: fullAnswer,
          isStreaming: false,
          citations: citations,
        });
      } else {
        // Fallback to non-streaming mode for compatibility
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
      }
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
                  {msg.isStreaming && (
                    <span
                      className="badge bg-info"
                      style={{ fontSize: "0.7rem" }}
                    >
                      Streaming...
                    </span>
                  )}
                </div>
                <ReactMarkdown>{msg.text}</ReactMarkdown>
                {msg.citations && msg.citations.length > 0 && (
                  <div
                    style={{
                      marginTop: "8px",
                      fontSize: "0.85rem",
                      color: "#666",
                      borderLeft: "2px solid #ddd",
                      paddingLeft: "8px",
                    }}
                  >
                    <strong>Sources:</strong>
                    {msg.citations.map((c, idx) => (
                      <div key={idx}>
                        - {c.source} (Page {c.page})
                      </div>
                    ))}
                  </div>
                )}
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
