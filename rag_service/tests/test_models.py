import pytest
from auth.models import User, UserRole

class TestUserModel:
    """Test User model functionality"""
    
    def test_user_creation(self, db_session):
        """Test creating a user"""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_password",
            full_name="Test User",
            role=UserRole.USER
        )
        
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        
        assert user.id is not None
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.role == UserRole.USER
        assert user.is_active is True
        assert user.is_verified is False
        assert user.created_at is not None
        assert user.updated_at is not None
    
    def test_user_role_properties(self):
        """Test user role property methods"""
        user = User(role=UserRole.USER)
        admin = User(role=UserRole.ADMIN)
        
        assert user.is_user is True
        assert user.is_admin is False
        
        assert admin.is_user is False
        assert admin.is_admin is True
    
    def test_user_permissions_user_role(self):
        """Test permissions for user role"""
        user = User(role=UserRole.USER, is_active=True)
        
        # User permissions
        assert user.has_permission("upload_pdf")
        assert user.has_permission("ask_question") 
        assert user.has_permission("summarize")
        assert user.has_permission("view_documents")
        
        # Admin-only permissions
        assert not user.has_permission("manage_users")
        assert not user.has_permission("delete_documents")
        assert not user.has_permission("view_all_documents")
    
    def test_user_permissions_admin_role(self):
        """Test permissions for admin role"""
        admin = User(role=UserRole.ADMIN, is_active=True)
        
        # Admin has all permissions
        assert admin.has_permission("upload_pdf")
        assert admin.has_permission("ask_question")
        assert admin.has_permission("summarize")
        assert admin.has_permission("view_documents")
        assert admin.has_permission("manage_users")
        assert admin.has_permission("delete_documents")
        assert admin.has_permission("view_all_documents")
        assert admin.has_permission("compare_documents")
    
    def test_inactive_user_permissions(self):
        """Test that inactive users have no permissions"""
        user = User(role=UserRole.USER, is_active=False)
        admin = User(role=UserRole.ADMIN, is_active=False)
        
        # Inactive users should have no permissions regardless of role
        assert not user.has_permission("upload_pdf")
        assert not user.has_permission("ask_question")
        assert not admin.has_permission("manage_users")
        assert not admin.has_permission("upload_pdf")
    
    def test_unknown_permission(self):
        """Test handling of unknown permissions"""
        user = User(role=UserRole.USER, is_active=True)
        admin = User(role=UserRole.ADMIN, is_active=True)
        
        # Unknown permissions should return False for users
        assert not user.has_permission("unknown_permission")
        
        # Admins should have all permissions, even unknown ones
        assert admin.has_permission("unknown_permission")
    
    def test_user_repr(self):
        """Test user string representation"""
        user = User(
            username="testuser",
            role=UserRole.USER,
            is_active=True
        )
        
        repr_str = repr(user)
        assert "testuser" in repr_str
        assert "user" in repr_str
        assert "True" in repr_str

class TestUserRole:
    """Test UserRole enum"""
    
    def test_user_role_values(self):
        """Test UserRole enum values"""
        assert UserRole.USER.value == "user"
        assert UserRole.ADMIN.value == "admin"
    
    def test_user_role_comparison(self):
        """Test UserRole comparison"""
        assert UserRole.USER == UserRole.USER
        assert UserRole.ADMIN == UserRole.ADMIN
        assert UserRole.USER != UserRole.ADMIN
    
    def test_user_role_extensibility(self):
        """Test that UserRole can be extended (documentation test)"""
        # This test documents that the enum is designed to be extensible
        # Future roles like MODERATOR, PREMIUM_USER can be added
        
        # Verify current roles exist
        assert hasattr(UserRole, 'USER')
        assert hasattr(UserRole, 'ADMIN')
        
        # Document expected future roles (commented in models.py)
        expected_future_roles = [
            'MODERATOR',
            'PREMIUM_USER', 
            'API_USER'
        ]
        
        # This test serves as documentation that these roles are planned
        for role in expected_future_roles:
            # These don't exist yet but are planned for future extension
            assert not hasattr(UserRole, role), f"If {role} is implemented, update this test"