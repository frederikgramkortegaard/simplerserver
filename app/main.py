"""The composition root: assemble the pieces and run.

Schema changes are Alembic migrations (migrations/versions/):
    .venv/bin/alembic revision --autogenerate -m "..."   after editing models
    .venv/bin/alembic upgrade head                       to apply

Run:  .venv/bin/python -m app.main           walkthrough (fresh db, migrated)
      .venv/bin/python -m app.main --serve   uvicorn on :8000
"""

import json
import pathlib
import sys

from starlette.applications import Starlette
from starlette.middleware import Middleware

from .db import DatabaseSession
from .routes import posts, relations, users

app = Starlette(
    routes=[*users.router.routes, *posts.router.routes, *relations.router.routes],
    middleware=[Middleware(DatabaseSession)],
)


def migrate() -> None:
    """Bring the database to the latest migration (alembic upgrade head)."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")


def main() -> None:
    """Narrated walkthrough exercising every route against the real app."""
    import httpx
    from starlette.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)

    def call(method: str, path: str, body=None, token=None) -> httpx.Response:
        """Fire one request, print the exchange, return the response."""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        suffix = f"  {json.dumps(body)}" if body is not None else ""
        print(f"  {method} {path}{suffix}")
        response = client.request(method, path, json=body, headers=headers)
        print(f"      -> {response.status_code} {response.text}")
        return response

    print("== signup ==")
    fred = call("POST", "/users", {"username": "frederik", "email": "fred@example.com", "full_name": "Frederik"}).json()
    bob = call("POST", "/users", {"username": "bob", "email": "bob@example.com", "full_name": "Bob"}).json()
    call("POST", "/users", {"username": "frederik", "email": "other@example.com", "full_name": "Imposter"})
    call("POST", "/users", {"username": "carol", "email": "not-an-email", "full_name": "Carol"})

    print("\n== auth is a header; /me is the authenticated pair ==")
    call("GET", "/me")
    call("GET", "/me", token=fred["api_token"])
    call("PATCH", "/me", {"full_name": "Frederik Gram"}, token=fred["api_token"])

    print("\n== posts: filtering, pagination, embeds, ownership ==")
    call("POST", "/posts", {"content": "hello world"}, token=fred["api_token"])
    call("POST", "/posts", {"content": "bob was here"}, token=bob["api_token"])
    call("POST", "/posts", {"content": "second post"}, token=fred["api_token"])
    call("GET", "/posts?limit=2")
    call("GET", "/posts?author_id=1&embed_author=true")
    call("GET", "/posts?limit=999")
    call("DELETE", "/posts/2", token=fred["api_token"])
    call("DELETE", "/posts/3", token=fred["api_token"])

    print("\n== relations: request, accept, list ==")
    call("POST", "/relations/bob", token=fred["api_token"])
    call("POST", "/relations/bob", token=fred["api_token"])
    call("POST", "/relations/frederik", token=fred["api_token"])
    call("POST", "/relations/ghost", token=fred["api_token"])
    call("POST", "/relations/frederik/accept", token=bob["api_token"])
    call("GET", "/relations", token=fred["api_token"])
    call("GET", "/relations", token=bob["api_token"])
    print()


if __name__ == "__main__":
    pathlib.Path("demo.db").unlink(missing_ok=True)  # fresh demo db each run
    migrate()
    if "--serve" in sys.argv:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        main()
