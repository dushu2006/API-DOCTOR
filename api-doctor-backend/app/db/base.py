from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

Base = declarative_base()


def _normalized_database_url() -> str:
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        raw = url.replace("sqlite:///", "", 1)
        db_path = Path(raw)
        if not db_path.is_absolute():
            # Resolve relative SQLite paths against the backend directory
            # so the database file lives alongside the app code and is
            # easy to find and inspect.
            db_path = Path(settings.BACKEND_ROOT) / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"
    return url


DATABASE_URL = _normalized_database_url()
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _migrate_missing_columns() -> None:
    """Add columns that exist in the SQLAlchemy model but not in the live table.

    ``Base.metadata.create_all`` only creates *new* tables; it never alters
    existing ones.  When new columns are added to a model after the table has
    already been created, SQLite will raise ``OperationalError: no such column``
    on every query that touches the new field.  This lightweight migration
    inspects every mapped table and issues ``ALTER TABLE … ADD COLUMN`` for any
    columns that are absent.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            if not insp.has_table(table_name):
                continue  # create_all will handle it

            existing_cols = {col["name"] for col in insp.get_columns(table_name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                # Build a minimal DDL type string from the column's type
                col_type = column.type.compile(dialect=engine.dialect)
                nullable = "" if column.nullable else " NOT NULL"
                default = ""
                if column.default is not None and hasattr(column.default, "arg"):
                    arg = column.default.arg
                    if isinstance(arg, str):
                        default = f" DEFAULT '{arg}'"
                    elif isinstance(arg, bool):
                        default = f" DEFAULT {1 if arg else 0}"
                    elif isinstance(arg, (int, float)):
                        default = f" DEFAULT {arg}"
                # If column is nullable and has no default, we can safely omit defaults
                if not default and not column.nullable:
                    # Provide a sensible empty default for non-nullable text/string columns
                    default = " DEFAULT ''"
                ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {col_type}{nullable}{default}'
                conn.execute(text(ddl))


def _remove_unmapped_tables() -> None:
    """Delete the obsolete durable workflow table and all data in it.

    Match its schema instead of deleting every unknown table: deployments may
    share a database with other applications, and unrelated tables must remain
    untouched.
    """
    from sqlalchemy import inspect, text

    signature = {
        "project_id",
        "detection",
        "stack_trace",
        "root_cause",
        "fix_proposal",
        "sandbox_result",
        "activity",
    }
    mapped = set(Base.metadata.tables)
    inspector = inspect(engine)
    preparer = engine.dialect.identifier_preparer
    with engine.begin() as connection:
        for table_name in inspector.get_table_names():
            if table_name.startswith("sqlite_") or table_name in mapped:
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            project_linked = any(
                foreign_key.get("referred_table") == "projects"
                for foreign_key in inspector.get_foreign_keys(table_name)
            )
            if project_linked and signature.issubset(columns):
                connection.execute(text(f"DROP TABLE IF EXISTS {preparer.quote(table_name)}"))


def init_db() -> None:
    from app.db import models  # noqa: F401

    _remove_unmapped_tables()
    Base.metadata.create_all(bind=engine)
    _migrate_missing_columns()
