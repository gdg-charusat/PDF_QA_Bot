# Authentication System Documentation

## Overview

The PDF QA Bot authentication system provides secure, role-based access control for all API endpoints. Built with industry-standard practices including JWT tokens, bcrypt password hashing, and SQLAlchemy ORM for security.

## Architecture

### Components

1. **Database Layer** (`database.py`):
   - SQLAlchemy configuration
   - Session management
   - Database dependency injection

2. **Models** (`auth/models.py`):
   - User model with role-based permissions
   - Extensible UserRole enum
   - Built-in permission system

3. **Security** (`auth/security.py`):
   - Password hashing with bcrypt
   - JWT token creation and validation
   - Security utilities and helpers

4. **Middleware** (`auth/middleware.py`):
   - Authentication middleware
   - Authorization decorators
   - Role and permission checking

5. **API Router** (`auth/router.py`):
   - Authentication endpoints
   - User management endpoints
   - Admin functionality

6. **Schemas** (`auth/schemas.py`):
   - Pydantic models for API requests/responses
   - Input validation
   - Data serialization

### Data Flow

```
Request → Middleware → Permission Check → Endpoint Handler → Response
   ↓           ↓             ↓                ↓
JWT Token → User Object → Role/Permission → Business Logic
```

## Configuration

### Environment Variables

| Variable                      | Description                | Default                                     | Required |
| ----------------------------- | -------------------------- | ------------------------------------------- | -------- |
| `SECRET_KEY`                  | JWT signing secret         | `your-secret-key-change-this-in-production` | Yes      |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT token expiration       | `30`                                        | No       |
| `DATABASE_URL`                | Database connection string | `sqlite:///./pdf_qa_bot.db`                 | No       |

### Security Configuration

```python
# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

## User Management

### User Model

```python
class User(Base):
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
```

### User Roles

```python
class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    # Future extensions:
    # MODERATOR = "moderator"
    # PREMIUM_USER = "premium_user"
    # API_USER = "api_user"
```

### Permission System

The permission system is role-based with extensible permissions:

```python
def has_permission(self, permission: str) -> bool:
    """Check if user has specific permission"""
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
    }

    return permission in role_permissions.get(self.role, set())
```

## API Authentication

### Request Format

All protected endpoints require the Authorization header:

```
Authorization: Bearer <JWT_TOKEN>
```

### JWT Token Structure

```json
{
  "sub": "123", // User ID
  "username": "john_doe", // Username
  "role": "user", // User role
  "is_active": true, // Account status
  "exp": 1640995200 // Expiration timestamp
}
```

### Authentication Flow

1. **Registration**: `POST /auth/register`

   ```json
   {
     "username": "john_doe",
     "email": "john@example.com",
     "password": "secure_password_123",
     "full_name": "John Doe",
     "role": "user"
   }
   ```

2. **Login**: `POST /auth/login`

   ```json
   {
     "username": "john_doe",
     "password": "secure_password_123"
   }
   ```

3. **Token Response**:

   ```json
   {
     "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
     "token_type": "bearer",
     "expires_in": 1800,
     "user": {
       "id": 1,
       "username": "john_doe",
       "email": "john@example.com",
       "role": "user",
       "is_active": true
     }
   }
   ```

4. **Authenticated Requests**:
   ```bash
   curl -H "Authorization: Bearer <token>" http://localhost:5000/upload
   ```

## Middleware Usage

### Authentication Dependencies

```python
from auth.middleware import (
    get_current_user,           # Get authenticated user
    require_user,               # Require USER or ADMIN role
    require_admin,              # Require ADMIN role only
    require_upload_permission,  # Require upload permission
    get_optional_user          # Optional authentication
)

# Basic authentication
@app.post("/protected-endpoint")
def protected_endpoint(current_user: User = Depends(get_current_user)):
    return {"user": current_user.username}

# Role-based access
@app.post("/admin-endpoint")
def admin_endpoint(admin_user: User = Depends(require_admin)):
    return {"message": "Admin access granted"}

# Permission-based access
@app.post("/upload")
def upload_file(current_user: User = Depends(require_upload_permission)):
    return {"uploaded_by": current_user.username}
```

### Custom Middleware

```python
# Custom role requirement
def require_roles(allowed_roles: List[UserRole]):
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Required roles: {[role.value for role in allowed_roles]}"
            )
        return current_user
    return role_checker

# Usage
require_moderator_or_admin = require_roles([UserRole.MODERATOR, UserRole.ADMIN])

@app.post("/moderate")
def moderate_content(user: User = Depends(require_moderator_or_admin)):
    return {"message": "Moderation access granted"}
```

## Database Operations

### Creating Users

```python
from auth.models import User, UserRole
from auth.security import SecurityManager

def create_user(db: Session, username: str, email: str, password: str, role: UserRole = UserRole.USER):
    hashed_password = SecurityManager.get_password_hash(password)

    user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
        role=role,
        is_active=True,
        is_verified=False
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user
```

### User Queries

```python
# Find user by username
user = db.query(User).filter(User.username == username).first()

# Find active users
active_users = db.query(User).filter(User.is_active == True).all()

# Find users by role
admins = db.query(User).filter(User.role == UserRole.ADMIN).all()

# Find users with specific permission
users_with_upload = [u for u in db.query(User).all() if u.has_permission("upload_pdf")]
```

## Security Best Practices

### Password Security

- **bcrypt**: Industry standard password hashing
- **Salt**: Automatic salt generation prevents rainbow table attacks
- **Cost Factor**: Configurable work factor for future-proofing

```python
# Password hashing
hashed = SecurityManager.get_password_hash("user_password")

# Password verification
is_valid = SecurityManager.verify_password("user_password", hashed)
```

### JWT Security

- **HS256 Algorithm**: Symmetric signing algorithm
- **Expiration**: Configurable token lifetime
- **Claims Validation**: Automatic expiration and signature verification

```python
# Token creation
token = SecurityManager.create_access_token({
    "sub": str(user.id),
    "username": user.username,
    "role": user.role.value
})

# Token validation
token_data = SecurityManager.verify_token(token)
```

### Rate Limiting

Authentication endpoints include rate limiting:

```python
@limiter.limit("10/15 minutes")  # 10 requests per 15 minutes
async def upload_file(request: Request, ...):
    pass

@limiter.limit("60/15 minutes")  # 60 requests per 15 minutes
def ask_question(request: Request, ...):
    pass
```

## Testing

### Test Structure

```
tests/
├── conftest.py              # Test configuration and fixtures
├── test_auth_endpoints.py   # Authentication API tests
├── test_security.py         # Security utilities tests
├── test_middleware.py       # Middleware tests
├── test_models.py          # Database model tests
└── test_protected_endpoints.py  # API protection tests
```

### Test Fixtures

```python
@pytest.fixture
def test_user(db_session):
    """Create a test user"""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=SecurityManager.get_password_hash("testpass123"),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    return user

@pytest.fixture
def auth_headers(test_user):
    """Create authorization headers"""
    token_data = SecurityManager.create_token_for_user(test_user)
    return {"Authorization": f"Bearer {token_data['access_token']}"}
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_auth_endpoints.py -v

# Test with coverage
pytest tests/ --cov=auth --cov-report=html
```

## Extension Guide

### Adding New Roles

1. **Update UserRole enum**:

   ```python
   class UserRole(str, enum.Enum):
       USER = "user"
       ADMIN = "admin"
       MODERATOR = "moderator"  # New role
   ```

2. **Update permission system**:

   ```python
   moderator_permissions = user_permissions.union({
       "moderate_content", "view_reports"
   })

   role_permissions = {
       UserRole.USER: user_permissions,
       UserRole.ADMIN: admin_permissions,
       UserRole.MODERATOR: moderator_permissions,  # New permissions
   }
   ```

3. **Create middleware**:
   ```python
   require_moderator = AuthMiddleware.require_roles([UserRole.MODERATOR, UserRole.ADMIN])
   ```

### Adding New Permissions

1. **Define permission**:

   ```python
   # Add to appropriate role permission sets
   new_permission = "export_data"
   ```

2. **Create middleware**:

   ```python
   require_export_permission = AuthMiddleware.require_permissions(["export_data"])
   ```

3. **Apply to endpoints**:
   ```python
   @app.post("/export")
   def export_data(user: User = Depends(require_export_permission)):
       pass
   ```

### OAuth Integration

The architecture supports OAuth2 integration:

1. **Add OAuth provider**:

   ```python
   from authlib.integrations.fastapi_oauth2 import OAuth2

   oauth = OAuth2()
   oauth.register('google', ...)
   ```

2. **Create OAuth endpoints**:

   ```python
   @app.get("/auth/google")
   async def google_login():
       return await oauth.google.authorize_redirect(request, redirect_uri)
   ```

3. **Handle OAuth callback**:
   ```python
   @app.get("/auth/callback")
   async def oauth_callback():
       # Process OAuth response
       # Create or update user
       # Return JWT token
   ```

## Troubleshooting

### Common Issues

1. **Token Validation Fails**:
   - Check SECRET_KEY matches between token creation and validation
   - Verify token hasn't expired
   - Ensure proper Authorization header format

2. **Permission Denied**:
   - Verify user has required role/permission
   - Check user is active (`is_active = True`)
   - Confirm endpoint has correct middleware

3. **Database Errors**:
   - Check database connection string
   - Verify database tables are created
   - Check user exists in database

### Debug Mode

Enable debug logging for authentication:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("auth")

# Add to middleware
logger.debug(f"Authenticating user: {token_data.username}")
logger.debug(f"User permissions: {user.role}")
```

## Migration Guide

### From v1.x to v2.x (Authentication Update)

1. **Install new dependencies**:

   ```bash
   pip install python-jose[cryptography] passlib[bcrypt] python-multipart sqlalchemy
   ```

2. **Update environment**:

   ```env
   SECRET_KEY=your-secure-secret-key
   ACCESS_TOKEN_EXPIRE_MINUTES=30
   DATABASE_URL=sqlite:///./pdf_qa_bot.db
   ```

3. **Create admin user**:

   ```bash
   curl -X POST "http://localhost:5000/auth/register" \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "email": "admin@company.com", "password": "secure123", "role": "admin"}'
   ```

4. **Update API calls**:

   ```bash
   # Old (v1.x)
   curl -X POST "http://localhost:5000/upload" -F "file=@doc.pdf"

   # New (v2.x)
   curl -X POST "http://localhost:5000/upload" \
     -H "Authorization: Bearer <token>" \
     -F "file=@doc.pdf"
   ```

5. **Legacy support**:
   - Use `/upload/anonymous` for temporary backward compatibility
   - Plan migration of all clients to authenticated endpoints
   - Deprecated endpoints will be removed in v3.x
