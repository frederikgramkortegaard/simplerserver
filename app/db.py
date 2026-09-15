"""Infrastructure: the engine, the per-request session, its lifecycle.

A dependency is an ordinary function call; the request is the scope.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

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
