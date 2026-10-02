"""The HTTP API (api.py), on a Store over a SQLite file in a temporary folder."""

import tempfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import api
from store import Store

KEY = "k" * 64


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "store", Store(f"sqlite:///{tempfile.mkdtemp()}/test.sqlite3"))
    monkeypatch.setattr(api, "API_KEY", KEY)
    with TestClient(api.app, headers={"X-API-Key": KEY}) as client:
        yield client


def make_item(client, name="first", data=None):
    return client.post("/items", json={"name": name, "data": data or {"n": 1}})


def test_every_route_but_health_needs_the_key(client, monkeypatch):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health", headers={"X-API-Key": ""}).status_code == 200
    for headers in ({"X-API-Key": ""}, {"X-API-Key": "wrong"}):
        response = client.get("/items", headers=headers)
        assert response.status_code == 401 and "X-API-Key" in response.json()["detail"]
    monkeypatch.setattr(api, "API_KEY", "")  # no key set lets nothing in
    assert client.get("/items", headers={"X-API-Key": ""}).status_code == 401


def test_item_lifecycle(client):
    created = make_item(client)
    assert created.status_code == 201
    item = created.json()
    assert item["name"] == "first" and item["data"] == {"n": 1}
    assert datetime.fromisoformat(item["created_at"]).tzinfo is not None
    assert client.get(f"/items/{item['id']}").json() == item

    renamed = client.patch(f"/items/{item['id']}", json={"name": "renamed"}).json()
    assert renamed["name"] == "renamed" and renamed["data"] == {"n": 1}  # data kept
    changed = client.patch(f"/items/{item['id']}", json={"data": {"n": 2}}).json()
    assert changed["name"] == "renamed" and changed["data"] == {"n": 2}

    assert client.delete(f"/items/{item['id']}").status_code == 204
    assert client.get(f"/items/{item['id']}").status_code == 404
    assert client.delete(f"/items/{item['id']}").status_code == 204  # a repeat is fine


def test_list_items_newest_first_in_pages(client):
    ids = [make_item(client, f"item {i}").json()["id"] for i in range(3)]
    assert [i["id"] for i in client.get("/items").json()] == ids[::-1]
    page = client.get("/items", params={"limit": 2, "offset": 1}).json()
    assert [i["id"] for i in page] == ids[1::-1]


def test_missing_items_are_404(client):
    assert client.get("/items/0000000000000000").status_code == 404
    missing = client.patch("/items/0000000000000000", json={"name": "x"})
    assert missing.status_code == 404 and "No item" in missing.json()["detail"]


def test_bad_requests_are_422(client):
    assert client.post("/items", json={"name": ""}).status_code == 422
    assert client.post("/items", json={"name": "a", "extra": 1}).status_code == 422
    assert client.post("/items", json={"name": "a", "data": [1, 2]}).status_code == 422
    item = make_item(client).json()
    assert client.patch(f"/items/{item['id']}", json={"colour": "red"}).status_code == 422
    assert client.get("/items", params={"limit": 0}).status_code == 422


def test_database_down_is_503(client, monkeypatch):
    monkeypatch.setattr(api, "store", Store("postgresql://u:p@127.0.0.1:1/db"))
    assert client.get("/health").status_code == 503
    response = client.get("/items")
    assert response.status_code == 503 and "unavailable" in response.json()["detail"]
