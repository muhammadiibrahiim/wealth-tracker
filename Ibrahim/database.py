"""
Database configuration and session management
"""
import os
from sqlmodel import SQLModel, Session, create_engine


# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wealth_tracker.db")

# Create engine with check_same_thread=False for SQLite
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=True, connect_args=connect_args)


def create_db_and_tables():
    """Initialize database tables"""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency to get database session"""
    with Session(engine) as session:
        yield session
