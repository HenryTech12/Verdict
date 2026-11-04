from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_compat_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    with engine.begin() as connection:
        if "disputes" in inspector.get_table_names() and "resolved_at" not in {column["name"] for column in inspector.get_columns("disputes") }:
            connection.execute(text("ALTER TABLE disputes ADD COLUMN resolved_at DATETIME"))
        if "audit_log" in inspector.get_table_names() and "duration_ms" not in {column["name"] for column in inspector.get_columns("audit_log") }:
            connection.execute(text("ALTER TABLE audit_log ADD COLUMN duration_ms INTEGER DEFAULT 0"))
