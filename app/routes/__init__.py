"""The routing mechanism, next to the routes that use it.

A Router collects routes declared beside their handlers and yields
ready-made Starlette Route objects. `endpoint` reads each handler's
signature: a model-annotated parameter is the request body (bad input
-> 422, handled at the parse site), the return annotation is the
response contract. Data lives in the signature; behavior stays in the
body — `request` is explicit, dependencies are ordinary calls.
"""

import functools
import json
from typing import get_type_hints

from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


def _is_model(hint):
    return isinstance(hint, type) and issubclass(hint, BaseModel)


def endpoint(fn):
    hints = get_type_hints(fn)
    response = hints.pop("return", None)
    response = response if _is_model(response) else None
    body_param = next((name for name, hint in hints.items() if _is_model(hint)), None)

    @functools.wraps(fn)
    async def wrapper(request):
        kwargs = {}
        if body_param is not None:
            try:
                kwargs[body_param] = hints[body_param].model_validate_json(await request.body())
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
            result = result.model_dump()
        return JSONResponse(result)

    return wrapper


class Router:
    def __init__(self):
        self.routes = []

    def get(self, path):
        return self._on("GET", path)

    def post(self, path):
        return self._on("POST", path)

    def put(self, path):
        return self._on("PUT", path)

    def patch(self, path):
        return self._on("PATCH", path)

    def delete(self, path):
        return self._on("DELETE", path)

    def _on(self, method, path):
        def decorator(fn):
            self.routes.append(Route(path, endpoint(fn), methods=[method]))
            return fn

        return decorator
