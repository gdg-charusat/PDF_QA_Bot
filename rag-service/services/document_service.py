"""
services/document_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Responsible for loading and chunking documents (PDF, DOCX, TXT, MD).

All heavy LangChain / pypdf imports are deferred to first use so the module
can be imported without those packages present (e.g., in lightweight test
environments).
"""

import logging
import os
from typing import Any, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import placeholders
# ---------------------------------------------------------------------------
_PyPDFLoader = None
_RecursiveCharacterTextSplitter = None


def _ensure_pdf_loader() -> bool:
    """Lazily import LangChain's PDF loader. Returns False if unavailable."""
    global _PyPDFLoader
    if _PyPDFLoader is not None:
        return True
    try:
        from langchain_community.document_loaders import PyPDFLoader  # type: ignore

        _PyPDFLoader = PyPDFLoader
        return True
    except Exception as exc:  # noqa: BLE001 – broken transitive deps can raise NameError etc.
        logger.warning("PyPDFLoader unavailable: %s", exc)
        return False


def _ensure_splitter() -> bool:
    """Lazily import LangChain's text splitter. Returns False if unavailable."""
    global _RecursiveCharacterTextSplitter
    if _RecursiveCharacterTextSplitter is not None:
        return True
    try:
        from langchain_text_splitters import (  # type: ignore
            RecursiveCharacterTextSplitter,
        )

        _RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter
        return True
    except Exception as exc:  # noqa: BLE001 – broken transitive deps can raise NameError etc.
        logger.warning("RecursiveCharacterTextSplitter unavailable: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Internal helper: minimal document wrapper used when LangChain is absent
# ---------------------------------------------------------------------------
class _SimpleDoc:
    """Minimal drop-in for a LangChain ``Document`` when the library is absent."""

    def __init__(self, text: str) -> None:
        self.page_content = text
        self.metadata: dict = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_pdf(file_path: str) -> List[Any]:
    """
    Load a PDF file and return a list of document objects.

    Falls back to the lightweight ``pypdf`` library when the LangChain loader
    is unavailable.

    Parameters
    ----------
    file_path:
        Absolute or relative path to the PDF file on disk.

    Returns
    -------
    list
        List of objects with a ``page_content`` attribute (one per page).
    """
    if _ensure_pdf_loader():
        loader = _PyPDFLoader(file_path)
        return loader.load()

    # Fallback: use pypdf directly
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(file_path)
        return [_SimpleDoc(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        logger.error("Failed to load PDF '%s': %s", file_path, exc)
        raise


def chunk_documents(
    docs: List[Any],
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
) -> List[Any]:
    """
    Split a list of document objects into smaller, overlapping chunks.

    Falls back to returning ``docs`` unchanged when LangChain's splitter is
    unavailable.

    Parameters
    ----------
    docs:
        Documents as returned by :func:`load_pdf` (or any loader).
    chunk_size:
        Maximum number of characters per chunk.
    chunk_overlap:
        Number of characters shared between consecutive chunks.

    Returns
    -------
    list
        List of chunked document objects.
    """
    if not _ensure_splitter():
        logger.warning("Text splitter unavailable; returning un-chunked docs.")
        return docs

    splitter = _RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return splitter.split_documents(docs)
