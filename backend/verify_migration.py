"""Verify T8-00 migration results."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text

async def verify():
    engine = create_async_engine('postgresql+asyncpg://postgres:postgres@localhost:5432/ai_tutor')
    session_factory = async_sessionmaker(engine)
    async with session_factory() as session:
        # Check question_images table
        r = await session.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'question_images' ORDER BY ordinal_position"
        ))
        print('=== question_images columns ===')
        for row in r:
            print(f'  {row[0]}: {row[1]}')

        # Check student_questions table
        r = await session.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'student_questions' ORDER BY ordinal_position"
        ))
        print('=== student_questions columns ===')
        for row in r:
            print(f'  {row[0]}: {row[1]}')

        # Check documents new columns
        r = await session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'documents' AND column_name IN ('subject', 'grade', 'category')"
        ))
        print('=== documents new columns ===')
        for row in r:
            print(f'  {row[0]}')

        # Check questions new columns
        r = await session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'questions' AND column_name IN ('text_description', 'image_enhanced_key', 'difficulty_level')"
        ))
        print('=== questions new columns ===')
        for row in r:
            print(f'  {row[0]}')

        # Check wrong_questions new columns
        r = await session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'wrong_questions' AND column_name IN ('mastery_level', 'review_count', 'last_review_at')"
        ))
        print('=== wrong_questions new columns ===')
        for row in r:
            print(f'  {row[0]}')

        # Check alembic version
        r = await session.execute(text("SELECT version_num FROM alembic_version"))
        v = r.scalar()
        print(f'\nAlembic version: {v}')

    await engine.dispose()

asyncio.run(verify())
