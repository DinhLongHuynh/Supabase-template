"""app-db: your app's database as an HTTP API, so that your app reaches its
data through the gateway's port (9876, the one the container publishes) at
/app-db/, on platforms where it can't open a Postgres connection.

    GET    /health             the database answers (no key needed)
    POST   /items              create an item                     201
    GET    /items              items, newest first (?limit=&offset=)
    GET    /items/{item_id}    one item                           404
    PATCH  /items/{item_id}    change an item's name or data      404
    DELETE /items/{item_id}    delete an item                     204
    GET    /docs               the OpenAPI docs (no key needed)

The items routes are an example: replace them with your own, and their
tables in models.py. Every route but /health and /docs needs the X-API-Key
header set to APP_DB_API_KEY, because the gateway is public. Errors are
FastAPI's ``{"detail": message}``; a 503 means the database is down. Times are
ISO 8601, in UTC. The queries are in store.py, the tables in models.py.
"""

import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field

from store import Conflict, NotFound, Store, Unavailable

DATABASE_URL = os.getenv("DATABASE_URL", "")
API_KEY = os.getenv("APP_DB_API_KEY", "")

store = Store(DATABASE_URL)
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not API_KEY:
        logger.error("APP_DB_API_KEY is not set: every request that needs it is refused.")
    try:
        store.ensure_schema()
    except Unavailable:
        logger.warning("The database is unreachable; the first request that needs it tries again.")
    yield


app = FastAPI(
    title="app-db",
    version="1.0.0",
    description="Your app's data, in Postgres, over HTTP.",
    lifespan=lifespan,
)


def _error(status: int):
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status)

    return handler


app.add_exception_handler(NotFound, _error(404))
app.add_exception_handler(Conflict, _error(409))
app.add_exception_handler(Unavailable, _error(503))

_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_key(supplied: Optional[str] = Security(_key_header)) -> None:
    """Router dependency: the X-API-Key header must be APP_DB_API_KEY.
    With no key set, nothing gets in."""
    if not API_KEY or not hmac.compare_digest((supplied or "").encode(), API_KEY.encode()):
        raise HTTPException(401, "Missing or wrong X-API-Key header.")


router = APIRouter(dependencies=[Depends(require_key)])


@app.get("/health")
def health() -> Dict[str, str]:
    """Readiness: the database answers, on the latest schema. 503 if not."""
    store.ping()
    return {"status": "ok"}


# Request bodies. Unknown fields are a 422, not silently dropped. The lengths
# are the columns' (models.py).


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemCreate(Body):
    name: str = Field(min_length=1, max_length=200)
    data: Dict[str, Any] = Field(default_factory=dict, description="Any JSON object.")


class ItemUpdate(Body):
    """A field left out (or null) stays as it is."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    data: Optional[Dict[str, Any]] = None


# Items: the example routes.


@router.post("/items", status_code=201)
def create_item(body: ItemCreate) -> Dict[str, Any]:
    """Create an item."""
    return store.create_item(**body.model_dump())


@router.get("/items")
def list_items(
    limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)
) -> List[Dict[str, Any]]:
    """Items, newest first, a page at a time."""
    return store.list_items(limit=limit, offset=offset)


@router.get("/items/{item_id}")
def get_item(item_id: str) -> Dict[str, Any]:
    """One item."""
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(404, "No such item.")
    return item


@router.patch("/items/{item_id}")
def update_item(item_id: str, body: ItemUpdate) -> Dict[str, Any]:
    """Change an item's name, its data, or both."""
    return store.update_item(item_id, **body.model_dump())


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str) -> Response:
    """Delete an item. Deleting one that is gone is fine."""
    store.delete_item(item_id)
    return Response(status_code=204)


app.include_router(router)
