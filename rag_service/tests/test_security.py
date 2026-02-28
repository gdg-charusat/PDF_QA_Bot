import pytest
from auth.security import SecurityManager
from auth.schemas import TokenData

class TestSecurityManager:
    """Test security utilities"""
    
    def test_password_hashing(self):
        """Test password hashing and verification"""
        password = "test_password_123"
        
        # Test hashing
        hashed = SecurityManager.get_password_hash(password)
        assert hashed != password
        assert len(hashed) > 0
        
        # Test verification
        assert SecurityManager.verify_password(password, hashed)
        assert not SecurityManager.verify_password("wrong_password", hashed)
    
    def test_token_creation_and_verification(self):
        """Test JWT token creation and verification"""
        # Create token
        test_data = {
            "sub": "123",
            "username": "testuser",
            "role": "user"
        }
        
        token = SecurityManager.create_access_token(test_data)
        assert isinstance(token, str)
        assert len(token) > 0
        
        # Verify token
        token_data = SecurityManager.verify_token(token)
        assert token_data is not None
        assert token_data.user_id == 123
        assert token_data.username == "testuser"
        assert token_data.role == "user"
    
    def test_invalid_token_verification(self):
        """Test verification of invalid tokens"""
        # Test invalid token
        invalid_token = "invalid.token.here"
        token_data = SecurityManager.verify_token(invalid_token)
        assert token_data is None
        
        # Test malformed token
        malformed_token = "not.a.jwt"
        token_data = SecurityManager.verify_token(malformed_token)
        assert token_data is None
    
    def test_create_token_for_user(self, test_user):
        """Test token creation for user object"""
        token_info = SecurityManager.create_token_for_user(test_user)
        
        assert "access_token" in token_info
        assert "token_type" in token_info
        assert "expires_in" in token_info
        assert token_info["token_type"] == "bearer"
        assert token_info["expires_in"] > 0
        
        # Verify the created token
        token_data = SecurityManager.verify_token(token_info["access_token"])
        assert token_data is not None
        assert token_data.user_id == test_user.id
        assert token_data.username == test_user.username