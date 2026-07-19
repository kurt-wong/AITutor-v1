"""
Domains - Bounded Context Organization

This module organizes code by business domains following DDD principles.
Each domain contains its own models, repositories, and services.

Domains:
- document: Document processing, OCR, question extraction
- question: Question management, classification, solutions
- knowledge: Knowledge system, knowledge tree
- embedding: Vector embeddings, similarity search
- wrong_question: Wrong question detection, tracking
- training: Training sets, mock exams
- system: System configuration, cost tracking
"""

from app.domains import document
from app.domains import question
from app.domains import knowledge
from app.domains import embedding
from app.domains import wrong_question
from app.domains import training
from app.domains import system

__all__ = [
    "document",
    "question",
    "knowledge",
    "embedding",
    "wrong_question",
    "training",
    "system",
]
