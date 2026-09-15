
import inspect
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field

from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, validates

# ======================================================================
# The framework. All of it.
# ======================================================================


class HTTPError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class Request:
    method: str
    path: str
    path_params: dict = field(default_factory=dict)
    body: object = None
    cache: dict = field(default_factory=dict)


@dataclass
class Response:
    status: int
    body: object


class App:
    def __init__(self):
        self._routes = []
        self._middlewares = []

    def get(self, path):
        return self._register("GET", path)

    def post(self, path):
        return self._register("POST", path)

    def delete(self, path):
        return self._register("DELETE", path)

    def middleware(self, fn):
        self._middlewares.append(fn)
        return fn

    def _register(self, method, path):
        pattern = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path) + "$")

        def decorator(fn):
            self._routes.append((method, pattern, inspect.signature(fn), fn))
            return fn

        return decorator

    def handle(self, method, path, body=None):
        request = Request(method, path, body=body)
        chain = self._dispatch
        for mw in reversed(self._middlewares):
            chain = (lambda m, nxt: lambda req: m(req, nxt))(mw, chain)
        return chain(request)

    def _dispatch(self, request):
        for method, pattern, sig, fn in self._routes:
            match = pattern.match(request.path)
            if method == request.method and match is not None:
                request.path_params = match.groupdict()
                return self._call(sig, fn, request)
        return Response(404, {"error": f"no route for {request.method} {request.path}"})

    def _call(self, sig, fn, request):
        try:
            kwargs = {}
            for name, param in sig.parameters.items():
                annotation = param.annotation
                if annotation is Request or name == "request":
                    kwargs[name] = request
                elif name in request.path_params:
                    raw = request.path_params[name]
                    kwargs[name] = raw if annotation is sig.empty else annotation(raw)
                elif isinstance(annotation, type) and param.default is sig.empty:
                    if request.body is None:
                        raise HTTPError(422, f"{name}: request body required")
                    body = request.body
                    kwargs[name] = annotation(**body) if isinstance(body, dict) else annotation(body)
            result = fn(**kwargs)
        except HTTPError as exc:
            return Response(exc.status, {"error": exc.detail})
        except (TypeError, ValueError) as exc:
            return Response(422, {"error": str(exc)})
        return result if isinstance(result, Response) else Response(200, result)

    def serve(self, host="127.0.0.1", port=8000):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlparse

        app = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                response = app.handle(self.command, urlparse(self.path).path, body=body)
                payload = json.dumps(response.body, indent=2).encode()
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_DELETE = _handle

        print(f"serving on http://{host}:{port}")
        ThreadingHTTPServer((host, port), Handler).serve_forever()


# ======================================================================
# The app.
# ======================================================================


class Username(str):
    def __init__(self, value):
        if not 3 <= len(self) <= 32:
            raise ValueError(f"invalid username: {value!r}")


class UserInput:
    """What the client sends — no id yet."""

    def __init__(self, username, age):
        self.username = Username(username)
        self.age = int(age)


class Base(DeclarativeBase):
    pass


class User(Base):
    """What we store — a real table row."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    age: Mapped[int]

    @validates("username")
    def _validate_username(self, key, value):
        return Username(value)  # the type still owns the invariant


engine = create_engine("sqlite:///demo.db", connect_args={"check_same_thread": False})


def get_db(request):
    if "db" not in request.cache:
        request.cache["db"] = Session(engine)
    return request.cache["db"]


app = App()


@app.middleware
def database_session(request, call_next):
    response = call_next(request)
    db = request.cache.get("db")
    if db is not None:
        db.commit() if response.status < 400 else db.rollback()
        db.close()
    return response


@app.post("/users")
def create_user(user: UserInput, request: Request):
    db = get_db(request)
    if db.scalar(select(User).where(User.username == user.username)) is not None:
        raise HTTPError(409, f"username {user.username!r} is taken")
    row = User(username=user.username, age=user.age)
    db.add(row)
    db.flush()  # the database assigns row.id
    return {"id": row.id, "username": row.username, "age": row.age}


@app.delete("/users")
def delete_user(user: User, request: Request):
    db = get_db(request)
    row = db.get(User, user.id)
    if row is None:
        raise HTTPError(404, f"no user {user.id}")
    db.delete(row)
    return {"deleted": user.id}


# ======================================================================
# Walkthrough.
# ======================================================================


def call(method, path, body=None):
    suffix = f"  {json.dumps(body)}" if body is not None else ""
    print(f"  {method} {path}{suffix}")
    response = app.handle(method, path, body=body)
    print(f"      -> {response.status} {json.dumps(response.body)}")


def main():
    print("== the type validates itself ==")
    try:
        Username("x")
    except ValueError as exc:
        print(f"  Username('x')  !!  ValueError: {exc}")

    print("\n== create_user(user: UserInput) ==")
    call("POST", "/users", {"username": "frederik", "age": 27})
    call("POST", "/users", {"username": "bob", "age": 34})
    call("POST", "/users", {"username": "frederik", "age": 30})
    call("POST", "/users", {"username": "x", "age": 27})
    call("POST", "/users", {"username": "frederik"})

    print("\n== delete_user(user: User) ==")
    call("DELETE", "/users", {"id": 1})
    call("DELETE", "/users", {"id": 1})
    print()


if __name__ == "__main__":
    pathlib.Path("demo.db").unlink(missing_ok=True)
    Base.metadata.create_all(engine)
    app.serve() if "--serve" in sys.argv else main()
