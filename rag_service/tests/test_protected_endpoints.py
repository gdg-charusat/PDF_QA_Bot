import pytest
from fastapi import status
from unittest.mock import patch, mock_open

class TestProtectedEndpoints:
    """Test that existing endpoints are properly protected"""
    
    def test_upload_requires_authentication(self, client, test_pdf_file):
        """Test that upload endpoint requires authentication"""
        with open(test_pdf_file, "rb") as f:
            response = client.post("/upload", files={"file": ("test.pdf", f, "application/pdf")})
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_upload_with_authentication(self, client, test_pdf_file, test_user, auth_headers):
        """Test upload with proper authentication"""
        # Mock the PDF processing to avoid actual ML operations
        with patch('main.process_pdf_internal') as mock_process:
            mock_process.return_value = {"message": "PDF processed successfully", "doc_id": "test-doc-id"}
            
            with open(test_pdf_file, "rb") as f:
                response = client.post(
                    "/upload", 
                    files={"file": ("test.pdf", f, "application/pdf")},
                    headers=auth_headers
                )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "doc_id" in data
        assert data["uploaded_by"] == test_user.username
        assert data["user_id"] == test_user.id
    
    def test_upload_non_pdf_file(self, client, auth_headers):
        """Test upload with non-PDF file"""
        fake_file_content = b"This is not a PDF file"
        
        response = client.post(
            "/upload",
            files={"file": ("test.txt", fake_file_content, "text/plain")},
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "error" in data
        assert "Only PDF files are supported" in data["error"]
    
    def test_ask_requires_authentication(self, client):
        """Test that ask endpoint requires authentication"""
        question_data = {
            "question": "What is this document about?",
            "doc_ids": ["test-doc-id"]
        }
        
        response = client.post("/ask", json=question_data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_ask_with_authentication(self, client, test_user, auth_headers):
        """Test ask endpoint with authentication"""
        # Mock the vector store and generation
        with patch('main.VECTOR_STORE') as mock_vector_store, \
             patch('main.generate_response') as mock_generate:
            
            # Mock similarity search
            mock_doc = type('MockDoc', (), {
                'page_content': 'Test content',
                'metadata': {'doc_id': 'test-doc-id'}
            })()
            mock_vector_store.similarity_search.return_value = [mock_doc]
            
            # Mock response generation
            mock_generate.return_value = "This is a test answer"
            
            question_data = {
                "question": "What is this document about?",
                "doc_ids": ["test-doc-id"]
            }
            
            response = client.post("/ask", json=question_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "answer" in data
    
    def test_ask_no_vector_store(self, client, auth_headers):
        """Test ask endpoint when no documents are uploaded"""
        with patch('main.VECTOR_STORE', None):
            question_data = {
                "question": "What is this document about?",
                "doc_ids": ["test-doc-id"]
            }
            
            response = client.post("/ask", json=question_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "Please upload at least one PDF first!" in data["answer"]
    
    def test_summarize_requires_authentication(self, client):
        """Test that summarize endpoint requires authentication"""
        summarize_data = {"doc_ids": ["test-doc-id"]}
        
        response = client.post("/summarize", json=summarize_data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_summarize_with_authentication(self, client, auth_headers):
        """Test summarize endpoint with authentication"""
        with patch('main.VECTOR_STORE') as mock_vector_store, \
             patch('main.generate_response') as mock_generate:
            
            # Mock similarity search
            mock_doc = type('MockDoc', (), {
                'page_content': 'Test content for summarization',
                'metadata': {'doc_id': 'test-doc-id'}
            })()
            mock_vector_store.similarity_search.return_value = [mock_doc]
            
            # Mock response generation
            mock_generate.return_value = "This is a test summary"
            
            summarize_data = {"doc_ids": ["test-doc-id"]}
            
            response = client.post("/summarize", json=summarize_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "summary" in data
    
    def test_compare_requires_authentication(self, client):
        """Test that compare endpoint requires authentication"""
        compare_data = {"doc_ids": ["doc1", "doc2"]}
        
        response = client.post("/compare", json=compare_data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_compare_with_authentication(self, client, auth_headers):
        """Test compare endpoint with authentication"""
        with patch('main.VECTOR_STORE') as mock_vector_store, \
             patch('main.DOCUMENT_REGISTRY') as mock_registry, \
             patch('main.generate_response') as mock_generate:
            
            # Mock document registry
            mock_registry.get.return_value = {"filename": "test.pdf"}
            
            # Mock similarity search
            mock_doc = type('MockDoc', (), {
                'page_content': 'Test content for comparison',
                'metadata': {'doc_id': 'doc1'}
            })()
            mock_vector_store.similarity_search.return_value = [mock_doc, mock_doc]
            
            # Mock response generation
            mock_generate.return_value = "This is a test comparison"
            
            compare_data = {"doc_ids": ["doc1", "doc2"]}
            
            response = client.post("/compare", json=compare_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "comparison" in data
    
    def test_documents_requires_authentication(self, client):
        """Test that documents endpoint requires authentication"""
        response = client.get("/documents")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_documents_with_authentication(self, client, test_user, auth_headers):
        """Test documents endpoint with authentication"""
        with patch('main.DOCUMENT_REGISTRY', {"doc1": {"filename": "test.pdf"}}):
            response = client.get("/documents", headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "documents" in data
        assert data["requested_by"] == test_user.username
    
    def test_similarity_matrix_requires_authentication(self, client):
        """Test that similarity-matrix endpoint requires authentication"""
        response = client.get("/similarity-matrix")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_similarity_matrix_with_authentication(self, client, test_user, auth_headers):
        """Test similarity-matrix endpoint with authentication"""
        with patch('main.DOCUMENT_EMBEDDINGS', {}) as mock_embeddings:
            # Test with insufficient documents
            response = client.get("/similarity-matrix", headers=auth_headers)
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "error" in data
            assert "At least 2 documents required" in data["error"]
    
    def test_process_pdf_requires_authentication(self, client):
        """Test that process-pdf endpoint requires authentication"""
        pdf_data = {"filePath": "/path/to/test.pdf"}
        
        response = client.post("/process-pdf", json=pdf_data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_process_pdf_with_authentication(self, client, test_user, auth_headers):
        """Test process-pdf endpoint with authentication"""
        with patch('main.process_pdf_internal') as mock_process:
            mock_process.return_value = {"message": "PDF processed successfully", "doc_id": "test-doc-id"}
            
            pdf_data = {"filePath": "/path/to/test.pdf"}
            
            response = client.post("/process-pdf", json=pdf_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "doc_id" in data
        assert data["processed_by"] == test_user.username
        assert data["user_id"] == test_user.id

class TestRoleBasedAccess:
    """Test role-based access control"""
    
    def test_user_permissions(self, test_user):
        """Test user role permissions"""
        assert test_user.has_permission("upload_pdf")
        assert test_user.has_permission("ask_question")
        assert test_user.has_permission("summarize")
        assert test_user.has_permission("view_documents")
        
        # Users should not have admin permissions
        assert not test_user.has_permission("manage_users")
        assert not test_user.has_permission("delete_documents")
    
    def test_admin_permissions(self, test_admin):
        """Test admin role permissions"""
        # Admin should have all permissions
        assert test_admin.has_permission("upload_pdf")
        assert test_admin.has_permission("ask_question")
        assert test_admin.has_permission("summarize")
        assert test_admin.has_permission("view_documents")
        assert test_admin.has_permission("manage_users")
        assert test_admin.has_permission("delete_documents")
        assert test_admin.has_permission("compare_documents")
    
    def test_inactive_user_permissions(self, test_user):
        """Test that inactive users have no permissions"""
        test_user.is_active = False
        
        # Inactive users should have no permissions
        assert not test_user.has_permission("upload_pdf")
        assert not test_user.has_permission("ask_question")
        assert not test_user.has_permission("summarize")

class TestLegacyEndpoints:
    """Test deprecated/legacy endpoints"""
    
    def test_anonymous_upload_deprecated(self, client, test_pdf_file):
        """Test that anonymous upload endpoint works but is deprecated"""
        with patch('main.process_pdf_internal') as mock_process:
            mock_process.return_value = {"message": "PDF processed successfully", "doc_id": "test-doc-id"}
            
            with open(test_pdf_file, "rb") as f:
                response = client.post(
                    "/upload/anonymous", 
                    files={"file": ("test.pdf", f, "application/pdf")}
                )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "doc_id" in data
        # Should not contain user info for anonymous uploads
        assert "uploaded_by" not in data
        assert "user_id" not in data