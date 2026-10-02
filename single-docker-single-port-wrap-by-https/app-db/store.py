"""Your app's data, in the Postgres database at DATABASE_URL. Every read and
write that api.py serves goes through here. The tables are in models.py,
their migrations in migrations/.

The schema is brought up to date at startup, or on the first call if the
database was down then, so the service starts whether or not it is up. A call
made while it is down raises Unavailable, and the next one tries again.
"""

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, TypeVar

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, delete, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import Session, sessionmaker

from models import Item

ROOT = Path(__file__).resolve().parent
CONNECT_TIMEOUT_S = 3

logger = logging.getLogger("uvicorn.error")
T = TypeVar("T")


class Conflict(Exception):
    """The change clashes with what is stored, e.g. a unique value already in
    use. The example table has no such constraint; your own tables may."""


class NotFound(Exception):
    """The row a change is for doesn't exist."""


class Unavailable(Exception):
    """The database is down, too slow, or failing on its side."""


def _get_one(db: Session, model: type[T], key: str) -> T:
    """The ``model`` row with primary key ``key``, else NotFound."""
    row = db.get(model, key)
    if row is None:
        raise NotFound(f"No {model.__name__.lower()} with id {key!r}.")
    return row


def make_engine(url: str) -> Engine:
    """An engine for ``url``: the Postgres database, or the tests' SQLite file."""
    # Postgres URLs start with postgresql:// (or postgres://); SQLAlchemy would
    # read those as psycopg2, but the installed driver is psycopg 3.
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.get_backend_name() != "sqlite":
        return create_engine(
            parsed, pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_S}
        )

    # Requests run on a thread pool, so connections move between threads;
    # timeout is how long a writer waits for another one's lock.
    engine = create_engine(parsed, connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")  # off by default, and per connection
        cursor.close()

    return engine


def _item(item: Item) -> Dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "data": item.data,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


class Store:
    def __init__(self, url: str) -> None:
        """:param url: DATABASE_URL. Empty makes every call fail as unavailable."""
        self.engine = make_engine(url) if url else None
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._migrated = False
        self._migrate_lock = threading.Lock()

    def ensure_schema(self) -> None:
        """Bring the schema up to the latest migration, once per process.

        :raises Unavailable: if the database can't be reached.
        """
        if self._migrated:
            return
        with self._migrate_lock, self._errors():
            if not self._migrated:
                config = Config(str(ROOT / "alembic.ini"))
                config.set_main_option("script_location", str(ROOT / "migrations"))
                with self.engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
                self._migrated = True
                logger.info("Database %s is at the latest schema", self.engine.url.render_as_string())

    @contextmanager
    def _errors(self) -> Iterator[None]:
        """Turn the database's failures into this module's exceptions."""
        if self.engine is None:
            logger.error("DATABASE_URL is not set.")
            raise Unavailable("The database is not configured.")
        try:
            yield
        except IntegrityError as exc:
            # A uniqueness or foreign key constraint said no, possibly because
            # two requests raced past the same check.
            raise Conflict("The change conflicts with the stored data.") from exc
        except (DBAPIError, PoolTimeout) as exc:
            logger.warning("Database call failed: %s", exc)
            raise Unavailable("The database is unavailable right now.") from exc

    @contextmanager
    def _db(self) -> Iterator[Session]:
        """A session for one call, on an up-to-date schema."""
        self.ensure_schema()
        with self._errors(), self._sessions() as session:
            yield session

    def ping(self) -> None:
        """Check that the database answers, on an up-to-date schema.

        :raises Unavailable: if it doesn't.
        """
        with self._db() as db:
            db.execute(text("select 1"))

    # Items: the example table. Add methods like these for your own.

    def create_item(self, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        with self._db() as db:
            item = Item(name=name, data=data)
            db.add(item)
            db.commit()
            return _item(item)

    def list_items(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Items, newest first, a page at a time."""
        with self._db() as db:
            items = db.scalars(
                select(Item)
                .order_by(Item.created_at.desc(), Item.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return [_item(item) for item in items]

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as db:
            item = db.get(Item, item_id)
            return _item(item) if item else None

    def update_item(
        self,
        item_id: str,
        *,
        name: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Change an item. A field left as None stays as it is.

        :raises NotFound: if there is no such item.
        """
        with self._db() as db:
            item = _get_one(db, Item, item_id)
            if name is not None:
                item.name = name
            if data is not None:
                item.data = data
            db.commit()
            return _item(item)

    def delete_item(self, item_id: str) -> None:
        """Delete an item. Deleting one that is gone is fine."""
        with self._db() as db:
            db.execute(delete(Item).where(Item.id == item_id))
            db.commit()
