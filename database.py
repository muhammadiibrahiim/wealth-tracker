"""
Database configuration and session management
"""
import os
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import event


# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wealth_tracker.db")

# Create engine with check_same_thread=False for SQLite
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=True, connect_args=connect_args)


# SQLite does not enforce ON DELETE CASCADE / SET NULL unless foreign_keys is
# turned on per-connection. Without this, deleting a parent row silently leaves
# child rows behind (e.g. journal_lines surviving a journal_entries delete),
# which would corrupt party ledgers.
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()


def create_db_and_tables():
    """Initialize database tables"""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency to get database session"""
    with Session(engine) as session:
        yield session
