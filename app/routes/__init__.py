"""The routing mechanism, next to the routes that use it.

A Router collects routes declared beside their handlers and yields
ready-made Starlette Route objects. `endpoint` reads each handler's
signature: a model-annotated parameter is the request contract — parsed
from the JSON body, or from the query string on GET/DELETE — and the
return annotation is the response contract (bad input -> 422, handled
at the parse site). Data lives in the signature; behavior stays in the
body — `request` is explicit, dependencies are ordinary calls.
"""

import functools
import json
from collections.abc import Callable
from typing import get_type_hints

from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


def _is_model(hint) -> bool:
    """True if the annotation is a pydantic model class."""
    return isinstance(hint, type) and issubclass(hint, BaseModel)


def _dump(value):
    """A JSON-ready version of `value` (models become plain dicts)."""
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def endpoint(fn) -> Callable:
    """Wrap a handler so its signature's contracts are honored."""
    hints = get_type_hints(fn)
    response = hints.pop("return", None)
    response = response if _is_model(response) else None
    param = next((name for name, hint in hints.items() if _is_model(hint)), None)

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
        if isinstance(result, list):
            result = [_dump(item) for item in result]
        return JSONResponse(_dump(result))

    return wrapper


class Router:
    """Collects routes declared beside their handlers."""

    def __init__(self) -> None:
        """Start with no routes."""
        self.routes = []

    def get(self, path: str) -> Callable:
        """Register a GET route at `path`."""
        return self._on("GET", path)

    def post(self, path: str) -> Callable:
        """Register a POST route at `path`."""
        return self._on("POST", path)

    def put(self, path: str) -> Callable:
        """Register a PUT route at `path`."""
        return self._on("PUT", path)

    def patch(self, path: str) -> Callable:
        """Register a PATCH route at `path`."""
        return self._on("PATCH", path)

    def delete(self, path: str) -> Callable:
        """Register a DELETE route at `path`."""
        return self._on("DELETE", path)

    def _on(self, method: str, path: str) -> Callable:
        """Build the decorator that records the route."""

        def decorator(fn) -> Callable:
            """Record the route; the handler itself is returned unchanged."""
            self.routes.append(Route(path, endpoint(fn), methods=[method]))
            return fn

        return decorator
