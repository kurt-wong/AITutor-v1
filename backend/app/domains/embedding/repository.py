"""
Embedding Repository

Database operations for question_embeddings table.
Per DSD §17.8: create, get_by_question, search_by_vector
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.embedding.models import QuestionEmbedding


class EmbeddingRepository:
    """Repository for embedding CRUD and vector search."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        question_id: int,
        vector: list[float],
        embedding_provider: str | None = None,
        embedding_dimension: int | None = None,
    ) -> QuestionEmbedding:
        """Create or update embedding for a question."""
        existing = await self.get_by_question(question_id)
        if existing:
            existing.embedding = vector
            existing.embedding_provider = embedding_provider
            existing.embedding_dimension = embedding_dimension
            await self.session.flush()
            return existing

        emb = QuestionEmbedding(
            question_id=question_id,
            embedding=vector,
            embedding_provider=embedding_provider,
            embedding_dimension=embedding_dimension,
        )
        self.session.add(emb)
        await self.session.flush()
        return emb

    async def get_by_question(self, question_id: int) -> QuestionEmbedding | None:
        """Get embedding by question ID."""
        result = await self.session.execute(
            select(QuestionEmbedding).where(QuestionEmbedding.question_id == question_id)
        )
        return result.scalar_one_or_none()

    async def search_similar(self, question_id: int, top_k: int = 5) -> list[dict]:
        """Search similar questions via pgvector cosine similarity.

        Returns list of {"question_id": int, "similarity": float}
        """
        source = await self.get_by_question(question_id)
        if not source:
            return []

        # pgvector cosine distance: 1 - cosine_similarity
        # Use SQLAlchemy cast with pgvector Vector type for proper serialization
        from sqlalchemy import select

        source_vec = list(source.embedding) if not isinstance(source.embedding, list) else source.embedding
        stmt = (
            select(
                QuestionEmbedding.question_id,
                (1 - QuestionEmbedding.embedding.cosine_distance(source_vec)).label("similarity"),
            )
            .where(QuestionEmbedding.question_id != question_id)
            .order_by(QuestionEmbedding.embedding.cosine_distance(source_vec))
            .limit(top_k)
        )
        result = await self.session.execute(stmt)
        return [{"question_id": row[0], "similarity": round(row[1], 4)} for row in result.fetchall()]
