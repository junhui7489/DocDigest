"""Database initialisation script.

Usage:
    python -m scripts.init_db

Creates all tables and enables the pgvector extension.
"""

import asyncio
import logging

from sqlalchemy import text

from app.models.database import Base, engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_db():
    """Create database tables and extensions."""
    async with engine.begin() as conn:
        # Enable pgvector
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        logger.info("pgvector extension enabled.")

        # Import all models so they register with Base.metadata
        import app.models.schemas  # noqa: F401

        # Create tables
        await conn.run_sync(Base.metadata.create_all)
        logger.info("All tables created successfully.")

    logger.info("Database initialisation complete.")


if __name__ == "__main__":
    asyncio.run(init_db())
