"""The real Store, on a SQLite file in a temporary folder. To run these on
Postgres, set TEST_DATABASE_URL to a throwaway database: every table is
emptied after each test."""

import os
import re
import tempfile

import pytest
from sqlalchemy import delete, text

from models import Item
from store import NotFound, Store, Unavailable, make_engine


@pytest.fixture(scope="module")
def client():
    url = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{tempfile.mkdtemp()}/test.sqlite3"
    client = Store(url)
    client.ensure_schema()
    return client


@pytest.fixture(autouse=True)
def empty_database(client):
    yield
    with client.engine.begin() as connection:
        connection.execute(delete(Item))


# Setup


def test_postgres_urls_use_psycopg():
    for url in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        assert make_engine(url).url.drivername == "postgresql+psycopg"


def test_schema_is_at_the_latest_migration(client):
    with client.engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == "0001"


def test_database_down_is_unavailable():
    down = Store("postgresql://u:p@127.0.0.1:1/db")
    with pytest.raises(Unavailable, match="database is unavailable"):
        down.list_items()
    with pytest.raises(Unavailable):  # and the next call tries again
        down.ping()
    with pytest.raises(Unavailable):
        Store("").list_items()


# Items


def test_create_and_get(client):
    item = client.create_item("first", {"tags": ["a", "b"]})
    assert re.fullmatch("[0-9a-f]{16}", item["id"])
    assert item["created_at"].tzinfo is not None
    assert client.get_item(item["id"]) == item
    assert client.get_item("0000000000000000") is None


def test_update_changes_only_what_is_given(client):
    item = client.create_item("first", {"n": 1})
    renamed = client.update_item(item["id"], name="renamed")
    assert renamed["name"] == "renamed" and renamed["data"] == {"n": 1}
    assert renamed["updated_at"] >= item["updated_at"]
    changed = client.update_item(item["id"], data={"n": 2})
    assert changed["name"] == "renamed" and changed["data"] == {"n": 2}
    with pytest.raises(NotFound):
        client.update_item("0000000000000000", name="x")


def test_list_is_newest_first_in_pages(client):
    ids = [client.create_item(f"item {i}", {})["id"] for i in range(3)]
    assert [i["id"] for i in client.list_items()] == ids[::-1]
    assert [i["id"] for i in client.list_items(limit=1, offset=2)] == ids[:1]


def test_delete(client):
    item = client.create_item("first", {})
    client.delete_item(item["id"])
    assert client.get_item(item["id"]) is None
    client.delete_item(item["id"])  # a repeat is fine
