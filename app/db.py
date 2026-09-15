"""Infrastructure: the engine, the per-request session, its lifecycle.

A dependency is an ordinary function call; the request is the scope.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware

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
