import axios from "axios";

const API_BASE = process.env.REACT_APP_API_URL || "";

// Create axios instance with default config
const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 90000,
});

/**
 * Upload a document to the server
 * @param {File} file - The file to upload
 * @param {string} sessionId - Session identifier for isolation
 * @returns {Promise<{doc_id: string}>} Document ID from server
 */
export const uploadDocument = async (file, sessionId) => {
  if (!file) {
    throw new Error("No file provided");
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 90_000);

  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("sessionId", sessionId);

    const res = await apiClient.post("/upload", formData, {
      signal: controller.signal,
    });

    return {
      doc_id: res.data?.doc_id,
      name: file.name,
      url: URL.createObjectURL(file),
      ext: extractFileExtension(file.name),
    };
  } catch (error) {
    if (error.name === "AbortError" || error.code === "ECONNABORTED") {
      throw new Error("Upload timed out. Try a smaller document.");
    }
    throw new Error("Upload failed: " + (error.message || "Unknown error"));
  } finally {
    clearTimeout(timeoutId);
  }
};

/**
 * Ask a question about selected documents
 * @param {string} question - The question to ask
 * @param {string} sessionId - Session identifier
 * @param {string[]} doc_ids - Array of document IDs to query
 * @returns {Promise<{answer: string, confidence_score: number}>}
 */
export const askQuestion = async (question, sessionId, doc_ids) => {
  if (!question.trim()) {
    throw new Error("Question cannot be empty");
  }

  if (doc_ids.length === 0) {
    throw new Error("Please select at least one document");
  }

  if (question.length > 2000) {
    throw new Error("Question too long (max 2000 characters)");
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60_000);

  try {
    const res = await apiClient.post(
      "/ask",
      {
        question,
        sessionId,
        doc_ids,
      },
      { signal: controller.signal }
    );

    return {
      text: res.data.answer,
      confidence: res.data.confidence_score || 0,
    };
  } catch (error) {
    if (error.name === "AbortError" || error.code === "ECONNABORTED") {
      throw new Error("Request timed out.");
    }
    throw new Error("Error getting answer: " + (error.message || "Unknown error"));
  } finally {
    clearTimeout(timeoutId);
  }
};

/**
 * Ask a question with real-time token streaming (Issue #118)
 * Uses Server-Sent Events (SSE) to stream tokens as they're generated.
 * Provides chatGPT-like typing effect in the UI.
 * 
 * @param {string} question - The question to ask
 * @param {string[]} session_ids - Array of session IDs to query
 * @param {Function} onToken - Callback called for each token (receives token string)
 * @param {Function} onCitations - Callback called when citations arrive (receives citations array)
 * @returns {Promise<void>}
 */
export const askQuestionStream = async (question, session_ids, onToken, onCitations) => {
  if (!question.trim()) {
    throw new Error("Question cannot be empty");
  }

  if (session_ids.length === 0) {
    throw new Error("Please select at least one document");
  }

  if (question.length > 2000) {
    throw new Error("Question too long (max 2000 characters)");
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60_000);

  try {
    const response = await fetch(`${API_BASE}/ask-stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        question,
        session_ids,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Error streaming answer");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      
      // Keep the last incomplete line in the buffer
      buffer = lines[lines.length - 1];

      // Process complete SSE messages
      for (let i = 0; i < lines.length - 1; i++) {
        const line = lines[i].trim();
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            
            if (data.error) {
              throw new Error(data.error);
            }
            
            if (data.type === "metadata" && data.citations) {
              onCitations(data.citations);
            } else if (data.token) {
              onToken(data.token);
            } else if (data.done) {
              break;
            }
          } catch (e) {
            console.error("Error parsing SSE message:", e);
          }
        }
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("Request timed out.");
    }
    throw new Error(error.message || "Error streaming answer");
  } finally {
    clearTimeout(timeoutId);
  }
};

/**
 * Summarize selected documents
 * @param {string} sessionId - Session identifier
 * @param {string[]} doc_ids - Array of document IDs to summarize
 * @returns {Promise<{summary: string}>}
 */
export const summarizeDocuments = async (sessionId, doc_ids) => {
  if (doc_ids.length === 0) {
    throw new Error("Please select at least one document");
  }

  try {
    const res = await apiClient.post("/summarize", {
      sessionId,
      doc_ids,
    });

    return {
      text: res.data.summary,
    };
  } catch (error) {
    throw new Error("Error summarizing: " + (error.message || "Unknown error"));
  }
};

/**
 * Compare two documents
 * @param {string} sessionId - Session identifier
 * @param {string[]} doc_ids - Array of exactly 2 document IDs to compare
 * @returns {Promise<{comparison: string}>}
 */
export const compareDocuments = async (sessionId, doc_ids) => {
  if (doc_ids.length !== 2) {
    throw new Error("Please select exactly 2 documents to compare");
  }

  try {
    const res = await apiClient.post("/compare", {
      sessionId,
      doc_ids,
    });

    return {
      text: res.data.comparison || res.data.result || "",
    };
  } catch (error) {
    throw new Error("Error comparing documents: " + (error.message || "Unknown error"));
  }
};

/**
 * Extract file extension from filename
 * @param {string} filename - The filename
 * @returns {string} File extension (lowercase)
 */
const extractFileExtension = (filename) => {
  const dotIndex = filename.lastIndexOf(".");
  if (dotIndex !== -1 && dotIndex < filename.length - 1) {
    return filename.substring(dotIndex + 1).toLowerCase();
  }
  return "";
};

export default apiClient;
