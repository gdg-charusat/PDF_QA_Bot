from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.sql import func
from database import Base
import enum

class UserRole(str, enum.Enum):
    """Extensible user roles for future expansion"""
    USER = "user"
    ADMIN = "admin"
    # Future roles can be added here:
    # MODERATOR = "moderator" 
    # PREMIUM_USER = "premium_user"
    # API_USER = "api_user"

class User(Base):
    """User model with role-based access control"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<User(username='{self.username}', role='{self.role}', active={self.is_active})>"

    @property
    def is_admin(self):
        """Check if user has admin role"""
        return self.role == UserRole.ADMIN

    @property  
    def is_user(self):
        """Check if user has regular user role"""
        return self.role == UserRole.USER

    def has_permission(self, permission: str) -> bool:
        """
        Extensible permission system for future use
        Can be expanded to check specific permissions based on role
        """
        if not self.is_active:
            return False
            
        # Admin has all permissions
        if self.is_admin:
            return True
            
        # Define permission sets for each role
        user_permissions = {
            "upload_pdf", "ask_question", "summarize", "view_documents"
        }
        
        admin_permissions = user_permissions.union({
            "manage_users", "delete_documents", "view_all_documents", "compare_documents"
        })
        
        role_permissions = {
            UserRole.USER: user_permissions,
            UserRole.ADMIN: admin_permissions,
            # Future roles can define their permissions here
        }
        
        return permission in role_permissions.get(self.role, set())