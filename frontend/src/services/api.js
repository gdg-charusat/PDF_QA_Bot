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
