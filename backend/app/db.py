from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# (table, column, DDL type) additions applied to databases created by older versions.
_COMPAT_COLUMNS = [
    ("disputes", "resolved_at", "DATETIME"),
    ("audit_log", "duration_ms", "INTEGER DEFAULT 0"),
    ("approvals", "note", "TEXT"),
    ("approvals", "decided_by", "VARCHAR(80)"),
    ("assessments", "llm_error", "TEXT"),
    ("assessments", "token_usage", "JSON"),
    ("decisions", "rule_fired", "VARCHAR(80)"),
]


def ensure_compat_schema() -> None:
    if not _is_sqlite:
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, column, ddl in _COMPAT_COLUMNS:
            if table in tables and column not in {c["name"] for c in inspector.get_columns(table)}:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
