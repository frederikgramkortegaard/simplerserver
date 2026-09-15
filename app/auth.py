"""Auth. The current user is an ordinary function call — no Depends
chain — cached on the request so any number of calls cost one query.
"""

from sqlalchemy import select
from starlette.exceptions import HTTPException

from .db import get_db
from .models import User


async def current_user(request) -> User:
    """Resolve the Bearer token to a User; 401 if missing or invalid."""
    if not hasattr(request.state, "user"):
        token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(401, "missing bearer token")
        user = await get_db(request).scalar(select(User).where(User.api_token == token))
        if user is None:
            raise HTTPException(401, "invalid token")
        request.state.user = user
    return request.state.user
