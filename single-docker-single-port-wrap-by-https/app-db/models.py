"""The tables. Alembic migrations (migrations/) create and change them; the
service never runs DDL on its own.

    items   an example table: a name and a free-form JSON document. Replace
            it with your own tables, and add a migration for them.
"""

import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Index, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    """A random public id: 16 hex characters (64 bits), safe to put in URLs."""
    return secrets.token_hex(8)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stored as naive UTC (SQLite has no time zones), read back as aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: pass an aware one")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime}


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (Index("items_by_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
