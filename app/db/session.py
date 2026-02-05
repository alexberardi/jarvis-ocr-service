"""Database session configuration."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database URL from environment variable
# Docker: host.docker.internal, Local: localhost
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/jarvis_ocr"
)

# For Alembic migrations, use a different env var that points to localhost
MIGRATIONS_DATABASE_URL = os.getenv(
    "MIGRATIONS_DATABASE_URL",
    DATABASE_URL
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session_local():
    """Get the SessionLocal class for creating sessions."""
    return SessionLocal


def get_db():
    """Dependency for FastAPI to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
