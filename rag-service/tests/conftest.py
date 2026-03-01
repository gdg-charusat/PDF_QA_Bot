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
    """Create a temporary PDF file with real extractable text for testing.

    The PDF is built from raw bytes with a content stream so that PyPDFLoader
    can extract text and FAISS can index it.
    """

    def _build_pdf() -> bytes:
        """Return bytes of a minimal but valid PDF with extractable text."""
        body_text = (
            b"This is a sample PDF document created for automated testing. "
            b"It contains enough extractable text so that PyPDFLoader can "
            b"parse it, LangChain can split it into chunks, and FAISS can "
            b"build a non-empty vector store from those chunks. "
            b"Session isolation tests rely on at least one document chunk "
            b"being present so that similarity_search returns results."
        )
        stream_content = (
            b"BT\n/F1 12 Tf\n50 750 Td\n("
            + body_text
            + b") Tj\nET\n"
        )
        stream_len = len(stream_content)

        # --- assemble object bodies (no offsets yet) ---
        raw = {
            1: b"<</Type /Catalog /Pages 2 0 R>>",
            2: b"<</Type /Pages /Kids [3 0 R] /Count 1>>",
            # Page references content stream (4) and font resource (5)
            3: (
                b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
                b" /Contents 4 0 R"
                b" /Resources <</Font <</F1 5 0 R>>>>>>"
            ),
            4: (
                b"<</Length "
                + str(stream_len).encode()
                + b">>\nstream\n"
                + stream_content
                + b"\nendstream"
            ),
            5: (
                b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica"
                b" /Encoding /WinAnsiEncoding>>"
            ),
        }

        header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        buf = bytearray(header)
        offsets: dict[int, int] = {}
        for n in range(1, 6):
            offsets[n] = len(buf)
            buf += (str(n).encode() + b" 0 obj\n" + raw[n] + b"\nendobj\n")

        xref_offset = len(buf)
        xref = b"xref\n0 6\n" + b"0000000000 65535 f \n"
        for n in range(1, 6):
            xref += ("%010d 00000 n \n" % offsets[n]).encode()

        trailer = (
            b"trailer\n<</Size 6 /Root 1 0 R>>\nstartxref\n"
            + str(xref_offset).encode()
            + b"\n%%EOF\n"
        )
        return bytes(buf) + xref + trailer

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(_build_pdf())
        f.flush()
        yield f.name
    os.unlink(f.name)