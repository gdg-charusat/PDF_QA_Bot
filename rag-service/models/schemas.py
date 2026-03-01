"""
models/schemas.py
~~~~~~~~~~~~~~~~~
Pydantic request/response models for all API endpoints.
"""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Payload for the /ask endpoint."""

    question: str = Field(..., min_length=1, description="The question to answer.")
    session_ids: list[str] = Field(
        default_factory=list,
        description="List of session IDs whose documents should be searched.",
    )


class SummarizeRequest(BaseModel):
    """Payload for the /summarize endpoint."""

    session_ids: list[str] = Field(
        default_factory=list,
        description="List of session IDs to summarize.",
    )


class CompareRequest(BaseModel):
    """Payload for the /compare endpoint."""

    session_ids: list[str] = Field(
        default_factory=list,
        description="At least two session IDs to compare.",
    )
