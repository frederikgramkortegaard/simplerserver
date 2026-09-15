"""The composition root: assemble the pieces and run.

Run:  .venv/bin/python -m app.main           walkthrough
      .venv/bin/python -m app.main --serve   uvicorn on :8000
"""

import asyncio
import json
import pathlib
import sys

from starlette.applications import Starlette
from starlette.middleware import Middleware

from .db import DatabaseSession, engine
from .models import Base, Username
from .routes import users

app = Starlette(
    routes=users.router.routes,
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

    print("\n== create_user ==")
    call("POST", "/users", {"username": "frederik", "age": 27})
    call("POST", "/users", {"username": "bob", "age": 34})
    call("POST", "/users", {"username": "frederik", "age": 30})
    call("POST", "/users", {"username": "x", "age": 27})
    call("POST", "/users", {"username": "frederik"})
    call("POST", "/users", {"id": 999, "username": "mallory", "age": 30})

    print("\n== delete_user ==")
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
