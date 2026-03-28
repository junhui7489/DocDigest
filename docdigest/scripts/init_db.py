"""Database initialisation utility script.

This script is provided for manual / one-off database setup (e.g. local dev
or emergency re-initialisation). It is NOT used during normal application
startup — database initialisation is handled by the FastAPI lifespan context
manager in app/main.py so that the engine remains alive for the duration of
the process.

Usage:
    python -m scripts.init_db
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
