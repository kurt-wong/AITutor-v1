"""
Models - Compatibility Layer

This module provides backward compatibility for existing imports.
New code should import from app.domains.* directly.

Note: To avoid circular imports, this module only re-exports base classes.
Individual model classes should be imported from their domain modules.
"""

# Keep base imports
from app.models.base import Base, IDMixin, TimestampMixin  # noqa: F401

# Ensure all domain models are loaded before SQLAlchemy mapper initialization.
# These imports are required so that relationship string references
# (e.g. Mapped["Subject | None"], Mapped["Document | None"]) can be resolved.
import app.domains.document.models  # noqa: F401 - Document
import app.domains.embedding.models  # noqa: F401 - QuestionEmbedding
import app.domains.knowledge.models  # noqa: F401 - Subject, KnowledgeNode, QuestionKnowledge
import app.domains.question.models  # noqa: F401 - Question, QuestionImage, Solution
import app.domains.student.models  # noqa: F401 - StudentQuestion
import app.domains.system.models  # noqa: F401 - System models
import app.domains.training.models  # noqa: F401 - LearningRecord
import app.domains.wrong_question.models  # noqa: F401 - WrongQuestion
