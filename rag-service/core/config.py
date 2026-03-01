"""
core/config.py
~~~~~~~~~~~~~~
Centralised configuration: environment variables, logging setup, and the
SlowAPI rate-limiter instance that the rest of the application imports.
"""

import logging
import os

from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address

# ---------------------------------------------------------------------------
# Load .env (no-op if the file is absent)
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-driven settings
# ---------------------------------------------------------------------------
HF_GENERATION_MODEL: str = os.getenv(
    "HF_GENERATION_MODEL", "google/flan-t5-small"
)

SESSION_TIMEOUT: int = int(os.getenv("SESSION_TIMEOUT", "3600"))  # seconds

UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")

# ---------------------------------------------------------------------------
# Rate-limiter (shared singleton imported by api/routes.py and main.py)
# ---------------------------------------------------------------------------
limiter: Limiter = Limiter(key_func=get_remote_address)
