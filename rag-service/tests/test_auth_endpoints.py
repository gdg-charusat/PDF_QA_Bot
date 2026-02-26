import pytest
from fastapi import status

class TestAuthEndpoints:
    """Test authentication endpoints"""
    
    def test_user_registration_success(self, client, test_user_data):
        """Test successful user registration"""
        response = client.post("/auth/register", json=test_user_data)
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        
        assert data["username"] == test_user_data["username"]
        assert data["email"] == test_user_data["email"]
        assert data["full_name"] == test_user_data["full_name"]
        assert data["role"] == test_user_data["role"]
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data
        # Password should not be returned
        assert "password" not in data
        assert "hashed_password" not in data
    
    def test_user_registration_duplicate_username(self, client, test_user_data, test_user):
        """Test registration with duplicate username"""
        test_user_data["username"] = test_user.username
        test_user_data["email"] = "different@example.com"
        
        response = client.post("/auth/register", json=test_user_data)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Username already registered" in response.json()["detail"]
    
    def test_user_registration_duplicate_email(self, client, test_user_data, test_user):
        """Test registration with duplicate email"""
        test_user_data["username"] = "different_user"
        test_user_data["email"] = test_user.email
        
        response = client.post("/auth/register", json=test_user_data)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Email already registered" in response.json()["detail"]
    
    def test_user_registration_invalid_password(self, client, test_user_data):
        """Test registration with invalid password"""
        test_user_data["password"] = "short"  # Too short
        
        response = client.post("/auth/register", json=test_user_data)
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_user_login_success(self, client, test_user):
        """Test successful user login"""
        login_data = {
            "username": test_user.username,
            "password": "testpassword123"
        }
        
        response = client.post("/auth/login", json=login_data)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
        assert "user" in data
        assert data["user"]["username"] == test_user.username
    
    def test_user_login_invalid_username(self, client):
        """Test login with invalid username"""
        login_data = {
            "username": "nonexistent",
            "password": "password123"
        }
        
        response = client.post("/auth/login", json=login_data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid username or password" in response.json()["detail"]
    
    def test_user_login_invalid_password(self, client, test_user):
        """Test login with invalid password"""
        login_data = {
            "username": test_user.username,
            "password": "wrongpassword"
        }
        
        response = client.post("/auth/login", json=login_data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid username or password" in response.json()["detail"]
    
    def test_user_login_inactive_user(self, client, test_user):
        """Test login with inactive user"""
        # Deactivate user
        test_user.is_active = False
        
        login_data = {
            "username": test_user.username,
            "password": "testpassword123"
        }
        
        response = client.post("/auth/login", json=login_data)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "deactivated" in response.json()["detail"]
    
    def test_get_current_user_profile(self, client, test_user, auth_headers):
        """Test getting current user profile"""
        response = client.get("/auth/me", headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["username"] == test_user.username
        assert data["email"] == test_user.email
        assert data["id"] == test_user.id
    
    def test_get_current_user_profile_unauthorized(self, client):
        """Test getting profile without authentication"""
        response = client.get("/auth/me")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_get_current_user_profile_invalid_token(self, client):
        """Test getting profile with invalid token"""
        headers = {"Authorization": "Bearer invalid_token"}
        response = client.get("/auth/me", headers=headers)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_update_current_user_profile(self, client, test_user, auth_headers):
        """Test updating current user profile"""
        update_data = {
            "full_name": "Updated Name",
            "email": "updated@example.com"
        }
        
        response = client.put("/auth/me", json=update_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["full_name"] == update_data["full_name"]
        assert data["email"] == update_data["email"]
    
    def test_update_user_role_forbidden(self, client, test_user, auth_headers):
        """Test that regular users cannot change their role"""
        update_data = {"role": "admin"}
        
        response = client.put("/auth/me", json=update_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Cannot change your own role" in response.json()["detail"]
    
    def test_change_password_success(self, client, test_user, auth_headers):
        """Test successful password change"""
        password_data = {
            "current_password": "testpassword123",
            "new_password": "newpassword123"
        }
        
        response = client.post("/auth/change-password", json=password_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        assert "Password changed successfully" in response.json()["message"]
    
    def test_change_password_wrong_current(self, client, test_user, auth_headers):
        """Test password change with wrong current password"""
        password_data = {
            "current_password": "wrongpassword",
            "new_password": "newpassword123"
        }
        
        response = client.post("/auth/change-password", json=password_data, headers=auth_headers)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Current password is incorrect" in response.json()["detail"]

class TestAdminEndpoints:
    """Test admin-only endpoints"""
    
    def test_get_all_users_as_admin(self, client, test_admin, admin_headers):
        """Test getting all users as admin"""
        response = client.get("/auth/users", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) >= 1  # At least the admin user
    
    def test_get_all_users_as_user_forbidden(self, client, test_user, auth_headers):
        """Test that regular users cannot get all users"""
        response = client.get("/auth/users", headers=auth_headers)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_get_user_by_id_as_admin(self, client, test_user, test_admin, admin_headers):
        """Test getting user by ID as admin"""
        response = client.get(f"/auth/users/{test_user.id}", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["id"] == test_user.id
        assert data["username"] == test_user.username
    
    def test_get_nonexistent_user_by_id(self, client, test_admin, admin_headers):
        """Test getting nonexistent user by ID"""
        response = client.get("/auth/users/99999", headers=admin_headers)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_update_user_by_admin(self, client, test_user, test_admin, admin_headers):
        """Test updating user by admin"""
        update_data = {
            "role": "admin",
            "is_verified": True
        }
        
        response = client.put(f"/auth/users/{test_user.id}", json=update_data, headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["role"] == "admin"
        assert data["is_verified"] is True
    
    def test_deactivate_user_as_admin(self, client, test_user, test_admin, admin_headers):
        """Test deactivating user as admin"""
        response = client.post(f"/auth/users/{test_user.id}/deactivate", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        assert "deactivated successfully" in response.json()["message"]
    
    def test_activate_user_as_admin(self, client, test_user, test_admin, admin_headers):
        """Test activating user as admin"""
        # First deactivate
        test_user.is_active = False
        
        response = client.post(f"/auth/users/{test_user.id}/activate", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        assert "activated successfully" in response.json()["message"]
    
    def test_admin_cannot_deactivate_self(self, client, test_admin, admin_headers):
        """Test that admin cannot deactivate their own account"""
        response = client.post(f"/auth/users/{test_admin.id}/deactivate", headers=admin_headers)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot deactivate your own account" in response.json()["detail"]
    
    def test_delete_user_as_admin(self, client, test_user, test_admin, admin_headers):
        """Test deleting user as admin"""
        response = client.delete(f"/auth/users/{test_user.id}", headers=admin_headers)
        
        assert response.status_code == status.HTTP_200_OK
        assert "deleted successfully" in response.json()["message"]
    
    def test_admin_cannot_delete_self(self, client, test_admin, admin_headers):
        """Test that admin cannot delete their own account"""
        response = client.delete(f"/auth/users/{test_admin.id}", headers=admin_headers)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot delete your own account" in response.json()["detail"]