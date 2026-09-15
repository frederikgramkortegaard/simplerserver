"""Domain operations — plain async functions with honest signatures.

Errors are Starlette's own HTTPException, raised directly.
"""

from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from .models import User
from .schemas import UserInput


async def create_user(db, data: UserInput) -> User:
    user = User(username=data.username, age=data.age)
    db.add(user)
    try:
        await db.flush()  # INSERT runs here; the unique constraint decides
    except IntegrityError:
        raise HTTPException(409, f"username {data.username!r} is taken")
    return user


async def delete_user(db, id: int) -> User:
    user = await db.get(User, id)
    if user is None:
        raise HTTPException(404, f"no user {id}")
    await db.delete(user)
    return user
