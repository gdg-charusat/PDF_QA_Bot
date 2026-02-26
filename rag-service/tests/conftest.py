import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import tempfile
import os

from database import Base, get_db
from main import app
from auth.models import User, UserRole  
from auth.security import SecurityManager

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_pdf_qa_bot.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session")
def db_engine():
    """Create test database engine"""
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session(db_engine):
    """Create test database session"""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def override_get_db(db_session):
    """Override database dependency"""
    def _override():
        yield db_session
    return _override

@pytest.fixture  
def client(override_get_db):
    """Create test client with database override"""
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture
def test_user_data():
    """Test user registration data"""
    return {
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpassword123",
        "full_name": "Test User",
        "role": "user"
    }

@pytest.fixture
def test_admin_data():
    """Test admin registration data"""
    return {
        "username": "testadmin", 
        "email": "admin@example.com",
        "password": "adminpassword123",
        "full_name": "Test Admin",
        "role": "admin"
    }

@pytest.fixture
def test_user(db_session):
    """Create a test user in database"""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=SecurityManager.get_password_hash("testpassword123"),
        full_name="Test User",
        role=UserRole.USER,
        is_active=True,
        is_verified=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user

@pytest.fixture
def test_admin(db_session):
    """Create a test admin in database"""
    admin = User(
        username="testadmin",
        email="admin@example.com", 
        hashed_password=SecurityManager.get_password_hash("adminpassword123"),
        full_name="Test Admin",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin

@pytest.fixture
def user_token(test_user):
    """Create JWT token for test user"""
    token_data = SecurityManager.create_token_for_user(test_user)
    return token_data["access_token"]

@pytest.fixture  
def admin_token(test_admin):
    """Create JWT token for test admin"""
    token_data = SecurityManager.create_token_for_user(test_admin)
    return token_data["access_token"]

@pytest.fixture
def auth_headers(user_token):
    """Create authorization headers for user"""
    return {"Authorization": f"Bearer {user_token}"}

@pytest.fixture
def admin_headers(admin_token):
    """Create authorization headers for admin"""
    return {"Authorization": f"Bearer {admin_token}"}

@pytest.fixture
def test_pdf_file():
    """Create a temporary PDF file for testing"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        # Create a minimal PDF content (this is just for testing file upload)
        pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj  
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
>>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<<
/Size 4
/Root 1 0 R
>>
startxref
179
%%EOF"""
        f.write(pdf_content)
        f.flush()
        yield f.name
    os.unlink(f.name)