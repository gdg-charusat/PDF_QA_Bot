import React from "react";
import { Card, Form } from "react-bootstrap";

/**
 * DocumentSelector component
 * Displays a checklist for selecting documents
 */
const DocumentSelector = ({
  documents,
  selectedDocIds,
  onSelectionChange,
  cardClass,
}) => {
  const handleToggle = (docId) => {
    onSelectionChange(docId);
  };

  if (!documents || documents.length === 0) {
    return null;
  }

  return (
    <Card className={`mb-4 ${cardClass}`}>
      <Card.Body>
        <Card.Title>Select Documents</Card.Title>
        <Form>
          {documents.map((doc) => (
            <Form.Group key={doc.doc_id} className="mb-2">
              <Form.Check
                type="checkbox"
                id={`doc-${doc.doc_id}`}
                label={doc.name}
                checked={selectedDocIds.includes(doc.doc_id)}
                onChange={() => handleToggle(doc.doc_id)}
              />
            </Form.Group>
          ))}
        </Form>
      </Card.Body>
    </Card>
  );
};

export default DocumentSelector;
