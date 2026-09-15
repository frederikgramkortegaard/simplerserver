"""FastAPI-style Python without Annotated — Starlette + async SQLAlchemy.

Starlette is FastAPI *without* the FastAPI layer: no pydantic, no
Depends, no Annotated. Endpoints are async functions taking a request;
request.state is the per-request store. The idioms:

    types validate themselves       Username.__init__ raises ValueError
    the ORM row is the model        User(**await request.json())
    dependencies are ordinary calls get_db(request)
    lifecycle is middleware         commit/rollback/close
    ValueError -> 422               one exception handler

Run:  .venv/bin/python demo.py           walkthrough
      .venv/bin/python demo.py --serve   uvicorn on :8000
"""

import asyncio
import json
import pathlib
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route


class Username(str):
    def __init__(self, value):
        if not 3 <= len(self) <= 32:
            raise ValueError(f"invalid username: {value!r}")


class Base(DeclarativeBase):
    def to_dict(self):
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}


class User(Base):
    """The table row IS the model — one class for input, storage, output."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    age: Mapped[int]

    def __init__(self, username, age, id=None):
        super().__init__(id=id, username=username, age=int(age))

    @validates("username")
    def _validate_username(self, key, value):
        return Username(value)


engine = create_async_engine("sqlite+aiosqlite:///demo.db")


def get_db(request):
    if not hasattr(request.state, "db"):
        request.state.db = AsyncSession(engine)
    return request.state.db


class DatabaseSession(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        db = getattr(request.state, "db", None)
        if db is not None:
            await (db.commit() if response.status_code < 400 else db.rollback())
            await db.close()
        return response


async def create_user(request):
    try:
        user = User(**await request.json())  # construction is validation
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    db = get_db(request)
    if await db.scalar(select(User).where(User.username == user.username)) is not None:
        return JSONResponse({"error": f"username {user.username!r} is taken"}, status_code=409)
    db.add(user)
    await db.flush()
    return JSONResponse(user.to_dict())


async def delete_user(request):
    id = request.path_params["id"]  # already an int: the {id:int} converter
    db = get_db(request)
    user = await db.get(User, id)
    if user is None:
        return JSONResponse({"error": f"no user {id}"}, status_code=404)
    await db.delete(user)
    return JSONResponse({"deleted": id})


app = Starlette(
    routes=[
        Route("/users", create_user, methods=["POST"]),
        Route("/users/{id:int}", delete_user, methods=["DELETE"]),
    ],
    middleware=[Middleware(DatabaseSession)],
)


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def main():
    from starlette.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)

    def call(method, path, body=None):
        suffix = f"  {json.dumps(body)}" if body is not None else ""
        print(f"  {method} {path}{suffix}")
        response = client.request(method, path, json=body)
        print(f"      -> {response.status_code} {response.text}")

    print("== the type validates itself ==")
    try:
        Username("x")
    except ValueError as exc:
        print(f"  Username('x')  !!  ValueError: {exc}")

    print("\n== create_user: the body becomes the ORM row ==")
    call("POST", "/users", {"username": "frederik", "age": 27})
    call("POST", "/users", {"username": "bob", "age": 34})
    call("POST", "/users", {"username": "frederik", "age": 30})
    call("POST", "/users", {"username": "x", "age": 27})
    call("POST", "/users", {"username": "frederik"})

    print("\n== delete_user(id) ==")
    call("DELETE", "/users/1")
    call("DELETE", "/users/1")
    print()


if __name__ == "__main__":
    pathlib.Path("demo.db").unlink(missing_ok=True)
    asyncio.run(create_tables())
    if "--serve" in sys.argv:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        main()
