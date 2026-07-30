from datetime import datetime, timezone
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID


class Base(DeclarativeBase):
    """Base class for all database models."""
    
    # Custom type annotation map to always map datetime to timezone-aware UTC DateTime in PostgreSQL
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }


# SQLite compatibility rules for PostgreSQL-specific types during testing
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(32)"

