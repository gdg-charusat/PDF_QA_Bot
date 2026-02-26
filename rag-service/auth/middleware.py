from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import List, Optional, Callable
from functools import wraps
import inspect

from database import get_db
from auth.models import User, UserRole
from auth.security import SecurityManager
from auth.schemas import TokenData

# HTTP Bearer token scheme
security_scheme = HTTPBearer()

class AuthMiddleware:
    """Authentication and Authorization middleware"""
    
    @staticmethod
    def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
        db: Session = Depends(get_db)
    ) -> User:
        """Get current authenticated user from JWT token"""
        
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        try:
            # Extract token from Bearer scheme
            token = credentials.credentials
            token_data = SecurityManager.verify_token(token)
            
            if token_data is None or token_data.user_id is None:
                raise credentials_exception
                
        except Exception:
            raise credentials_exception
        
        # Get user from database
        user = db.query(User).filter(User.id == token_data.user_id).first()
        
        if user is None:
            raise credentials_exception
            
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated"
            )
            
        return user
    
    @staticmethod
    def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
        """Get current active user (alias for compatibility)"""
        return current_user
    
    @staticmethod
    def require_roles(allowed_roles: List[UserRole]):
        """Decorator to require specific roles for endpoint access"""
        def role_checker(current_user: User = Depends(get_current_user)) -> User:
            if current_user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied. Required roles: {[role.value for role in allowed_roles]}"
                )
            return current_user
        return role_checker
    
    @staticmethod  
    def require_permissions(required_permissions: List[str]):
        """Decorator to require specific permissions for endpoint access"""
        def permission_checker(current_user: User = Depends(get_current_user)) -> User:
            for permission in required_permissions:
                if not current_user.has_permission(permission):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Access denied. Missing permission: {permission}"
                    )
            return current_user
        return permission_checker
    
    @staticmethod
    def require_admin(current_user: User = Depends(get_current_user)) -> User:
        """Require admin role for endpoint access"""
        if not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        return current_user

class OptionalAuthMiddleware:
    """Optional authentication middleware for endpoints that can work with or without auth"""
    
    @staticmethod
    def get_optional_user(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
        db: Session = Depends(get_db)
    ) -> Optional[User]:
        """Get current user if token is provided, otherwise return None"""
        
        if credentials is None:
            return None
            
        try:
            token = credentials.credentials
            token_data = SecurityManager.verify_token(token)
            
            if token_data is None or token_data.user_id is None:
                return None
                
            user = db.query(User).filter(User.id == token_data.user_id).first()
            
            if user is None or not user.is_active:
                return None
                
            return user
            
        except Exception:
            return None

# Convenience dependencies for common use cases
require_user = AuthMiddleware.require_roles([UserRole.USER, UserRole.ADMIN])
require_admin = AuthMiddleware.require_admin 
get_current_user = AuthMiddleware.get_current_user
get_optional_user = OptionalAuthMiddleware.get_optional_user

# Permission-based dependencies  
require_upload_permission = AuthMiddleware.require_permissions(["upload_pdf"])
require_ask_permission = AuthMiddleware.require_permissions(["ask_question"])
require_summarize_permission = AuthMiddleware.require_permissions(["summarize"])
require_compare_permission = AuthMiddleware.require_permissions(["compare_documents"])
require_view_documents_permission = AuthMiddleware.require_permissions(["view_documents"])