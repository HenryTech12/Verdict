from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


# Render provides postgresql:// URLs. Explicitly select Psycopg 3.
database_url = settings.database_url

if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://", "postgresql+psycopg://", 1
    )
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

_is_sqlite = database_url.startswith("sqlite")

connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if _is_sqlite
    else {}
)

engine = create_engine(database_url, connect_args=connect_args)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
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


# (table, column, DDL type) additions for older database schemas.
_COMPAT_COLUMNS = [
    ("disputes", "resolved_at", "DATETIME"),
    ("disputes", "paypal_status", "VARCHAR(80)"),
    ("audit_log", "duration_ms", "INTEGER DEFAULT 0"),
    ("approvals", "note", "TEXT"),
    ("approvals", "decided_by", "VARCHAR(80)"),
    ("assessments", "llm_error", "TEXT"),
    ("assessments", "token_usage", "JSON"),
    ("decisions", "rule_fired", "VARCHAR(80)"),
]


def ensure_compat_schema() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table, column, ddl in _COMPAT_COLUMNS:
            if table not in tables:
                continue

            existing_columns = {
                item["name"] for item in inspect(connection).get_columns(table)
            }

            if column in existing_columns:
                continue

            if _is_sqlite:
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                )
            else:
                connection.execute(
                    text(
                        f"ALTER TABLE {table} "
                        f"ADD COLUMN IF NOT EXISTS {column} {ddl}"
                    )
                )

        # PostgreSQL supports changing an existing column's nullability.
        if not _is_sqlite and "disputes" in tables:
            connection.execute(
                text(
                    "ALTER TABLE disputes "
                    "ALTER COLUMN deadline DROP NOT NULL"
                )
            )