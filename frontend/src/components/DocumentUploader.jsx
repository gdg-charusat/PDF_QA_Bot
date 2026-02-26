import React, { useState } from "react";
import { Card, Button, Form, Spinner } from "react-bootstrap";
import { uploadDocument } from "../services/api";

/**
 * DocumentUploader component
 * Handles file input and upload with error handling
 */
const DocumentUploader = ({ onUploadSuccess, sessionId, darkMode, cardClass, inputClass }) => {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    try {
      const uploadedDoc = await uploadDocument(file, sessionId);
      
      // Call success callback with uploaded document data
      onUploadSuccess(uploadedDoc);
      
      setFile(null);
      alert("Document uploaded successfully!");
    } catch (error) {
      alert(error.message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <Card className={`mb-4 ${cardClass}`}>
      <Card.Body>
        <Card.Title>Upload Document</Card.Title>
        <Form>
          <Form.Group className="mb-3">
            <Form.Control
              type="file"
              className={inputClass}
              accept=".pdf,.docx,.txt,.md"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              disabled={uploading}
            />
          </Form.Group>
          <Button
            onClick={handleUpload}
            disabled={!file || uploading}
            variant="primary"
            className="w-100"
          >
            {uploading ? (
              <>
                <Spinner size="sm" animation="border" className="me-2" />
                Uploading...
              </>
            ) : (
              "Upload Document"
            )}
          </Button>
        </Form>
      </Card.Body>
    </Card>
  );
};

export default DocumentUploader;
