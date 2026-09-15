"""User operations."""

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from ..models import User
from ..schemas import UserInput, UserUpdate


async def create(db, data: UserInput) -> User:
    """Create a user with a fresh api token; 409 if username or email is taken."""
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
    return user


async def update(db, user: User, data: UserUpdate) -> User:
    """Apply the fields the client actually sent; 409 on an email collision."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)  # @validates guards each assignment
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(409, "email already taken")
    return user


async def by_username(db, username: str) -> User:
    """Fetch a user by username; 404 if there is none."""
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(404, f"no user {username!r}")
    return user


async def by_ids(db, ids: set[int]) -> dict[int, User]:
    """Fetch several users at once, keyed by id."""
    users = (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    return {user.id: user for user in users}
