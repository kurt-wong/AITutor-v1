"""
Document Pydantic Schemas

Request/response models for Document API endpoints.
Naming convention per DSD: <Entity>Create, <Entity>Response
"""

from datetime import datetime

from pydantic import BaseModel


class DocumentCreate(BaseModel):
    """Request model for document upload."""
    filename: str
    file_type: str


class DocumentResponse(BaseModel):
    """Response model for document details."""
    id: int
    filename: str
    file_type: str
    file_size: int
    object_key: str
    processing_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """Response model for document list."""
    documents: list[DocumentResponse]
    total: int
