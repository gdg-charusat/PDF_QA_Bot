import pytest
from fastapi import HTTPException
from unittest.mock import Mock
from auth.middleware import AuthMiddleware, OptionalAuthMiddleware
from auth.models import User, UserRole
from auth.security import SecurityManager

class TestAuthMiddleware:
    """Test authentication middleware"""
    
    def test_get_current_user_valid_token(self, db_session, test_user):
        """Test getting current user with valid token"""
        # Create a valid token
        token_data = SecurityManager.create_token_for_user(test_user)
        
        # Mock credentials
        mock_credentials = Mock()
        mock_credentials.credentials = token_data["access_token"]
        
        # Test middleware
        user = AuthMiddleware.get_current_user(mock_credentials, db_session)
        
        assert user.id == test_user.id
        assert user.username == test_user.username
        assert user.is_active is True
    
    def test_get_current_user_invalid_token(self, db_session):
        """Test getting current user with invalid token"""
        # Mock credentials with invalid token
        mock_credentials = Mock()
        mock_credentials.credentials = "invalid_token"
        
        # Test middleware - should raise exception
        with pytest.raises(HTTPException) as exc_info:
            AuthMiddleware.get_current_user(mock_credentials, db_session)
        
        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in str(exc_info.value.detail)
    
    def test_get_current_user_inactive_user(self, db_session, test_user):
        """Test getting inactive user"""
        # Deactivate user
        test_user.is_active = False
        db_session.commit()
        
        # Create token for inactive user
        token_data = SecurityManager.create_token_for_user(test_user)
        
        mock_credentials = Mock()
        mock_credentials.credentials = token_data["access_token"]
        
        # Should raise exception for inactive user
        with pytest.raises(HTTPException) as exc_info:
            AuthMiddleware.get_current_user(mock_credentials, db_session)
        
        assert exc_info.value.status_code == 403
        assert "deactivated" in str(exc_info.value.detail)
    
    def test_require_roles_user_allowed(self, test_user):
        """Test role requirement with allowed user role"""
        role_checker = AuthMiddleware.require_roles([UserRole.USER, UserRole.ADMIN])
        
        # Should return user without exception
        result = role_checker(test_user)
        assert result == test_user
    
    def test_require_roles_user_forbidden(self, test_user):
        """Test role requirement with forbidden user role"""
        role_checker = AuthMiddleware.require_roles([UserRole.ADMIN])
        
        # Should raise exception for insufficient role
        with pytest.raises(HTTPException) as exc_info:
            role_checker(test_user)
        
        assert exc_info.value.status_code == 403
        assert "Access denied" in str(exc_info.value.detail)
    
    def test_require_permissions_user_allowed(self, test_user):
        """Test permission requirement with allowed permission"""
        permission_checker = AuthMiddleware.require_permissions(["upload_pdf"])
        
        # Should return user without exception
        result = permission_checker(test_user)
        assert result == test_user
    
    def test_require_permissions_user_forbidden(self, test_user):
        """Test permission requirement with forbidden permission"""
        permission_checker = AuthMiddleware.require_permissions(["manage_users"])
        
        # Should raise exception for insufficient permission
        with pytest.raises(HTTPException) as exc_info:
            permission_checker(test_user)
        
        assert exc_info.value.status_code == 403
        assert "Missing permission: manage_users" in str(exc_info.value.detail)
    
    def test_require_admin_with_admin(self, test_admin):
        """Test admin requirement with admin user"""
        result = AuthMiddleware.require_admin(test_admin)
        assert result == test_admin
    
    def test_require_admin_with_user(self, test_user):
        """Test admin requirement with regular user"""
        with pytest.raises(HTTPException) as exc_info:
            AuthMiddleware.require_admin(test_user)
        
        assert exc_info.value.status_code == 403
        assert "Admin access required" in str(exc_info.value.detail)

class TestOptionalAuthMiddleware:
    """Test optional authentication middleware"""
    
    def test_get_optional_user_with_valid_token(self, db_session, test_user):
        """Test getting optional user with valid token"""
        # Create a valid token
        token_data = SecurityManager.create_token_for_user(test_user)
        
        # Mock credentials
        mock_credentials = Mock()
        mock_credentials.credentials = token_data["access_token"]
        
        # Test middleware
        user = OptionalAuthMiddleware.get_optional_user(mock_credentials, db_session)
        
        assert user is not None
        assert user.id == test_user.id
        assert user.username == test_user.username
    
    def test_get_optional_user_with_no_token(self, db_session):
        """Test getting optional user with no token"""
        # Test with None credentials
        user = OptionalAuthMiddleware.get_optional_user(None, db_session)
        
        assert user is None
    
    def test_get_optional_user_with_invalid_token(self, db_session):
        """Test getting optional user with invalid token"""
        # Mock credentials with invalid token
        mock_credentials = Mock()
        mock_credentials.credentials = "invalid_token"
        
        # Should return None instead of raising exception
        user = OptionalAuthMiddleware.get_optional_user(mock_credentials, db_session)
        
        assert user is None
    
    def test_get_optional_user_with_inactive_user(self, db_session, test_user):
        """Test getting optional user when user is inactive"""
        # Deactivate user
        test_user.is_active = False
        db_session.commit()
        
        # Create token for inactive user
        token_data = SecurityManager.create_token_for_user(test_user)
        
        mock_credentials = Mock()
        mock_credentials.credentials = token_data["access_token"]
        
        # Should return None for inactive user
        user = OptionalAuthMiddleware.get_optional_user(mock_credentials, db_session)
        
        assert user is None

class TestMiddlewareIntegration:
    """Test middleware integration and edge cases"""
    
    def test_middleware_with_nonexistent_user(self, db_session):
        """Test middleware behavior when token refers to nonexistent user"""
        # Create token for a user that doesn't exist in database
        token_data = {
            "sub": "99999",  # Non-existent user ID
            "username": "nonexistent",
            "role": "user"
        }
        token = SecurityManager.create_access_token(token_data)
        
        mock_credentials = Mock()
        mock_credentials.credentials = token
        
        # Should raise exception for nonexistent user
        with pytest.raises(HTTPException) as exc_info:
            AuthMiddleware.get_current_user(mock_credentials, db_session)
        
        assert exc_info.value.status_code == 401
    
    def test_middleware_with_malformed_token(self, db_session):
        """Test middleware with malformed JWT token"""
        mock_credentials = Mock()
        mock_credentials.credentials = "not.a.valid.jwt.token"
        
        # Should raise exception for malformed token
        with pytest.raises(HTTPException) as exc_info:
            AuthMiddleware.get_current_user(mock_credentials, db_session)
        
        assert exc_info.value.status_code == 401
    
    def test_middleware_with_expired_token(self, db_session, test_user):
        """Test middleware with expired token"""
        from datetime import datetime, timedelta
        
        # Create token that's already expired
        expired_data = {
            "sub": str(test_user.id),
            "username": test_user.username,
            "role": test_user.role.value,
            "exp": datetime.utcnow() - timedelta(hours=1)  # Expired 1 hour ago
        }
        
        from jose import jwt
        expired_token = jwt.encode(expired_data, "test-secret", algorithm="HS256")
        
        mock_credentials = Mock()
        mock_credentials.credentials = expired_token
        
        # Should raise exception for expired token
        with pytest.raises(HTTPException) as exc_info:
            AuthMiddleware.get_current_user(mock_credentials, db_session)
        
        assert exc_info.value.status_code == 401