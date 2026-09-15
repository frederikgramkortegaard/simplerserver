"""betterpython — a small social API with no Annotated and no Depends.

Everything is in this one file, in reading order: the endpoint wrapper
(the only "framework", one function), self-validating types, tables,
DTOs, infrastructure, endpoints, the route table, and a walkthrough.

The idioms:
    types validate themselves        plain __init__ raising ValueError
    signatures carry data contracts  a model param is the body (or the
                                     query string on GET/DELETE), the
                                     return annotation is the response
    behavior stays in the body       request is explicit, dependencies
                                     are ordinary calls: get_db(request)
    caching is request-scoped state  request.state
    lifecycle is middleware          commit / rollback / close
    errors are Starlette's own       raise HTTPException(409, ...)

Run:  .venv/bin/python demo.py           walkthrough
      .venv/bin/python demo.py --serve   uvicorn on :8000
"""

import asyncio
import enum
import functools
import inspect
import json
import pathlib
import re
import secrets
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import core_schema
from sqlalchemy import ForeignKey, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, validates
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

# ======================================================================
# The endpoint wrapper — the only "framework" here.
# ======================================================================


def endpoint(fn) -> Callable:
    """Wrap a handler so its signature's contracts are honored.

    A model-annotated parameter is the request contract — parsed from
    the JSON body, or from the query string on GET/DELETE — and the
    return annotation is the response contract. Bad input -> 422,
    handled right here at the parse site.
    """
    hints = get_type_hints(fn)
    response = hints.pop("return", None)
    if not (isinstance(response, type) and issubclass(response, BaseModel)):
        response = None
    param = next(
        (
            name
            for name, hint in hints.items()
            if isinstance(hint, type) and issubclass(hint, BaseModel)
        ),
        None,
    )

    @functools.wraps(fn)
    async def wrapper(request) -> Response:
        """Parse the request contract, call the handler, shape the response."""
        kwargs = {}
        if param is not None:
            model = hints[param]
            try:
                if request.method in ("GET", "DELETE"):
                    kwargs[param] = model.model_validate(dict(request.query_params))
                else:
                    kwargs[param] = model.model_validate_json(await request.body())
            except ValidationError as exc:
                return JSONResponse(
                    {"errors": json.loads(exc.json(include_url=False))}, status_code=422
                )
        result = await fn(request, **kwargs)
        if isinstance(result, Response):
            return result
        if response is not None:
            result = response.model_validate(result, from_attributes=True)
        if isinstance(result, BaseModel):
            result = result.model_dump(mode="json")
        elif isinstance(result, list):
            result = [item.model_dump(mode="json") for item in result]
        return JSONResponse(result)

    return wrapper


# ======================================================================
# Types — they validate themselves in plain __init__.
# ======================================================================


class Checked:
    """pydantic won't call arbitrary constructors without an opt-in; this
    mixin declares 'validate as the builtin, then construct me', so each
    type's invariant stays in its own plain __init__."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        """Tell pydantic to validate the builtin base, then call the class."""
        base = next(b for b in cls.__mro__ if b in (str, int, float, bytes))
        return core_schema.no_info_after_validator_function(cls, handler(base))


class Username(Checked, str):
    """A username: 3-32 characters."""

    def __init__(self, value) -> None:
        """Reject usernames outside 3-32 characters."""
        if not 3 <= len(self) <= 32:
            raise ValueError(f"invalid username: {value!r}")


class Email(Checked, str):
    """An email address (loosely checked — this is a demo)."""

    def __init__(self, value) -> None:
        """Reject strings that can't be email addresses."""
        if "@" not in self or len(self) > 254:
            raise ValueError(f"invalid email: {value!r}")


class Content(Checked, str):
    """Post content: 1-500 characters."""

    def __init__(self, value) -> None:
        """Reject empty or oversized content."""
        if not 1 <= len(self) <= 500:
            raise ValueError("post content must be 1-500 characters")


class Limit(Checked, int):
    """A page size: 1-100."""

    def __init__(self, value) -> None:
        """Reject page sizes outside 1-100."""
        if not 1 <= self <= 100:
            raise ValueError(f"limit must be between 1 and 100, got {self}")


class Offset(Checked, int):
    """A pagination offset: >= 0."""

    def __init__(self, value) -> None:
        """Reject negative offsets."""
        if self < 0:
            raise ValueError(f"offset must be >= 0, got {self}")


# ======================================================================
# Tables — the rows are the domain models.
# ======================================================================

Base = declarative_base()


class User(Base):
    """An account; api_token is how requests authenticate."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(unique=True)
    full_name: Mapped[str]
    api_token: Mapped[str] = mapped_column(unique=True)

    @validates("username")
    def _validate_username(self, key, value) -> Username:
        """Every write to `username` goes through the type."""
        return Username(value)

    @validates("email")
    def _validate_email(self, key, value) -> Email:
        """Every write to `email` goes through the type."""
        return Email(value)


class Post(Base):
    """A post authored by a user."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    @validates("content")
    def _validate_content(self, key, value) -> Content:
        """Every write to `content` goes through the type."""
        return Content(value)


class RelationState(enum.StrEnum):
    """The stored state of a relation edge."""

    pending = enum.auto()
    accepted = enum.auto()


class Relation(Base):
    """A friendship edge: pending until the addressee accepts."""

    __tablename__ = "relations"
    __table_args__ = (UniqueConstraint("from_id", "to_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    to_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(default=RelationState.pending)


# ======================================================================
# DTOs — what crosses the HTTP boundary. Inputs forbid extra fields
# (the declared fields are the whitelist); outputs can never leak a
# column they don't name.
# ======================================================================


class UserInput(BaseModel):
    """Signup payload."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    email: Email
    full_name: str


class UserUpdate(BaseModel):
    """Partial profile update — only the fields the client sends apply."""

    model_config = ConfigDict(extra="forbid")

    email: Email | None = None
    full_name: str | None = None


class SignupOutput(BaseModel):
    """The one response that ever includes the api token."""

    id: int
    username: Username
    email: Email
    full_name: str
    api_token: str


class MeOutput(BaseModel):
    """The authenticated user's own profile."""

    id: int
    username: Username
    email: Email
    full_name: str


class UserOutput(BaseModel):
    """The public shape of a user — no email, no token."""

    id: int
    username: Username
    full_name: str


class PostInput(BaseModel):
    """New-post payload."""

    model_config = ConfigDict(extra="forbid")

    content: Content


class PostQuery(BaseModel):
    """GET /posts query-string contract."""

    model_config = ConfigDict(extra="forbid")

    author_id: int | None = None
    limit: Limit = Limit(20)
    offset: Offset = Offset(0)
    embed_author: bool = False


class PostOutput(BaseModel):
    """A post; author is nested when ?embed_author=true."""

    id: int
    author_id: int
    content: Content
    created_at: datetime
    author: UserOutput | None = None


class RelationStatus(enum.StrEnum):
    """A relation as seen from one side of it."""

    pending_sent = enum.auto()
    pending_received = enum.auto()
    friends = enum.auto()


class RelationOutput(BaseModel):
    """A relation seen from the requesting user's side."""

    username: Username
    status: RelationStatus


# ======================================================================
# Infrastructure — db session per request, auth as an ordinary call.
# ======================================================================

engine = create_async_engine("sqlite+aiosqlite:///demo.db")


def get_db(request) -> AsyncSession:
    """The request's database session, opened on first use."""
    if not hasattr(request.state, "db"):
        request.state.db = AsyncSession(engine)
    return request.state.db


class DatabaseSession(BaseHTTPMiddleware):
    """Commit the request's session on success, roll back on error, close."""

    async def dispatch(self, request, call_next) -> Response:
        """Run the request, then settle its session (if one was opened)."""
        response = await call_next(request)
        db = getattr(request.state, "db", None)
        if db is not None:
            await (db.commit() if response.status_code < 400 else db.rollback())
            await db.close()
        return response


async def current_user(request) -> User:
    """Resolve the Bearer token to a User; 401 if missing or invalid.

    An ordinary function call — no Depends chain — cached on the request
    so any number of calls cost one query.
    """
    if not hasattr(request.state, "user"):
        token = (
            (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        )
        if not token:
            raise HTTPException(401, "missing bearer token")
        user = await get_db(request).scalar(select(User).where(User.api_token == token))
        if user is None:
            raise HTTPException(401, "invalid token")
        request.state.user = user
    return request.state.user


async def user_by_username(db, username: str) -> User:
    """Fetch a user by username; 404 if there is none."""
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(404, f"no user {username!r}")
    return user


async def users_by_ids(db, ids: set[int]) -> dict[int, User]:
    """Fetch several users at once, keyed by id."""
    users = (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    return {user.id: user for user in users}


# ======================================================================
# Endpoints.
# ======================================================================


async def signup(request, data: UserInput) -> SignupOutput:
    """Create an account; the response includes the api token, once."""
    db = get_db(request)
    user = User(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        api_token=secrets.token_hex(16),
    )
    db.add(user)
    try:
        await db.flush()  # the unique constraints decide
    except IntegrityError:
        raise HTTPException(409, "username or email already taken")
    return SignupOutput.model_validate(user, from_attributes=True)


async def me(request) -> MeOutput:
    """The authenticated user's own profile."""
    return MeOutput.model_validate(await current_user(request), from_attributes=True)


async def update_me(request, data: UserUpdate) -> MeOutput:
    """Partially update the authenticated user's profile."""
    user = await current_user(request)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)  # @validates guards each assignment

    try:
        await get_db(request).flush()
    except IntegrityError:
        raise HTTPException(409, "email already taken")

    return MeOutput.model_validate(user, from_attributes=True)


async def create_post(request, data: PostInput) -> PostOutput:
    """Create a post authored by the authenticated user."""
    author = await current_user(request)
    db = get_db(request)
    post = Post(author_id=author.id, content=data.content)
    db.add(post)
    await db.flush()
    return PostOutput.model_validate(post, from_attributes=True)


async def list_posts(request, query: PostQuery) -> list[PostOutput]:
    """List posts newest-first; ?author_id= filters, ?embed_author=true nests authors."""
    db = get_db(request)

    statement = (
        select(Post).order_by(Post.id.desc()).limit(query.limit).offset(query.offset)
    )
    if query.author_id is not None:
        statement = statement.where(Post.author_id == query.author_id)
    posts = (await db.scalars(statement)).all()

    outputs = [PostOutput.model_validate(post, from_attributes=True) for post in posts]
    if query.embed_author:
        authors = await users_by_ids(db, {post.author_id for post in posts})
        for output in outputs:
            output.author = UserOutput.model_validate(
                authors[output.author_id], from_attributes=True
            )

    return outputs


async def delete_post(request) -> dict:
    """Delete one of the authenticated user's own posts."""
    user = await current_user(request)
    db = get_db(request)

    post = await db.get(Post, request.path_params["id"])
    if post is None:
        raise HTTPException(404, f"no post {request.path_params['id']}")
    if post.author_id != user.id:
        raise HTTPException(403, "not your post")
    await db.delete(post)
    return {"deleted": post.id}


async def send_request(request) -> RelationOutput:
    """Send a friend request to `username`."""
    me = await current_user(request)
    db = get_db(request)
    username = request.path_params["username"]

    other = await user_by_username(db, username)
    if other.id == me.id:
        raise HTTPException(400, "cannot befriend yourself")

    existing = await db.scalar(
        select(Relation).where(
            ((Relation.from_id == me.id) & (Relation.to_id == other.id))
            | ((Relation.from_id == other.id) & (Relation.to_id == me.id))
        )
    )
    if existing is not None:
        raise HTTPException(409, f"relation with {username!r} already exists")

    db.add(Relation(from_id=me.id, to_id=other.id))
    await db.flush()
    return RelationOutput(username=username, status=RelationStatus.pending_sent)


async def accept_request(request) -> RelationOutput:
    """Accept the pending friend request from `username`."""
    me = await current_user(request)
    db = get_db(request)
    username = request.path_params["username"]

    other = await user_by_username(db, username)
    relation = await db.scalar(
        select(Relation).where(
            (Relation.from_id == other.id)
            & (Relation.to_id == me.id)
            & (Relation.status == RelationState.pending)
        )
    )
    if relation is None:
        raise HTTPException(404, f"no pending request from {username!r}")

    relation.status = RelationState.accepted
    await db.flush()
    return RelationOutput(username=username, status=RelationStatus.friends)


async def list_relations(request) -> list[RelationOutput]:
    """All of the authenticated user's relations, seen from their side."""
    me = await current_user(request)
    db = get_db(request)

    relations = (
        await db.scalars(
            select(Relation).where(
                (Relation.from_id == me.id) | (Relation.to_id == me.id)
            )
        )
    ).all()

    def other_id(relation: Relation) -> int:
        """The id of whoever isn't me on this edge."""
        return relation.to_id if relation.from_id == me.id else relation.from_id

    others = await users_by_ids(db, {other_id(r) for r in relations})

    outputs = []
    for relation in relations:
        if relation.status == RelationState.accepted:
            status = RelationStatus.friends
        elif relation.from_id == me.id:
            status = RelationStatus.pending_sent
        else:
            status = RelationStatus.pending_received
        outputs.append(
            RelationOutput(username=others[other_id(relation)].username, status=status)
        )
    return outputs


# ======================================================================
# Assembly — the route table doubles as the API's sitemap.
# ======================================================================

app = Starlette(
    routes=[
        Route("/users", endpoint(signup), methods=["POST"]),
        Route("/me", endpoint(me), methods=["GET"]),
        Route("/me", endpoint(update_me), methods=["PATCH"]),
        Route("/posts", endpoint(create_post), methods=["POST"]),
        Route("/posts", endpoint(list_posts), methods=["GET"]),
        Route("/posts/{id:int}", endpoint(delete_post), methods=["DELETE"]),
        Route("/relations", endpoint(list_relations), methods=["GET"]),
        Route("/relations/{username}", endpoint(send_request), methods=["POST"]),
        Route(
            "/relations/{username}/accept", endpoint(accept_request), methods=["POST"]
        ),
    ],
    middleware=[Middleware(DatabaseSession)],
)


# ======================================================================
# The spec — derived, never written.
# ======================================================================


def openapi() -> dict:
    """Derive the OpenAPI spec from the route table and the signatures.

    Nothing is annotated *for* this function; it reads the same hints
    `endpoint` already honors, so the spec cannot drift from the code.
    """
    paths = {}
    for route in app.routes:
        fn = inspect.unwrap(route.endpoint)
        hints = get_type_hints(fn)
        returns = hints.pop("return", None)
        model = next(
            (
                h
                for h in hints.values()
                if isinstance(h, type) and issubclass(h, BaseModel)
            ),
            None,
        )
        method = next(iter(route.methods - {"HEAD", "OPTIONS"})).lower()

        operation = {
            "summary": (fn.__doc__ or "").strip().splitlines()[0],
            "responses": {"200": {"description": "OK"}},
        }

        schema = None
        if isinstance(returns, type) and issubclass(returns, BaseModel):
            schema = returns.model_json_schema()
        elif get_origin(returns) is list:
            (item,) = get_args(returns)
            if isinstance(item, type) and issubclass(item, BaseModel):
                schema = {"type": "array", "items": item.model_json_schema()}
        if schema is not None:
            operation["responses"]["200"]["content"] = {
                "application/json": {"schema": schema}
            }

        parameters = [
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {
                    "type": "integer"
                    if type(conv).__name__ == "IntegerConvertor"
                    else "string"
                },
            }
            for name, conv in route.param_convertors.items()
        ]
        if model is not None:
            if method in ("get", "delete"):  # the model is the query contract
                model_schema = model.model_json_schema()
                required = set(model_schema.get("required", []))
                parameters += [
                    {
                        "name": name,
                        "in": "query",
                        "required": name in required,
                        "schema": prop,
                    }
                    for name, prop in model_schema.get("properties", {}).items()
                ]
            else:  # the model is the body contract
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {"schema": model.model_json_schema()}
                    },
                }
        if parameters:
            operation["parameters"] = parameters

        path = re.sub(r"\{(\w+):\w+\}", r"{\1}", route.path)
        paths.setdefault(path, {})[method] = operation

    return {
        "openapi": "3.1.0",
        "info": {"title": "betterpython", "version": "1.0"},
        "paths": paths,
    }


async def create_tables() -> None:
    """Create any missing tables (a real deployment would use Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ======================================================================
# Walkthrough.
# ======================================================================


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
    fred = call(
        "POST",
        "/users",
        {"username": "frederik", "email": "fred@example.com", "full_name": "Frederik"},
    ).json()
    bob = call(
        "POST",
        "/users",
        {"username": "bob", "email": "bob@example.com", "full_name": "Bob"},
    ).json()
    call(
        "POST",
        "/users",
        {"username": "frederik", "email": "other@example.com", "full_name": "Imposter"},
    )
    call(
        "POST",
        "/users",
        {"username": "carol", "email": "not-an-email", "full_name": "Carol"},
    )

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
    if "--openapi" in sys.argv:  # print the spec and exit: pipe to a file or CI
        print(json.dumps(openapi(), indent=2))
        sys.exit(0)
    pathlib.Path("demo.db").unlink(missing_ok=True)  # fresh demo db each run
    asyncio.run(create_tables())
    if "--serve" in sys.argv:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        main()
