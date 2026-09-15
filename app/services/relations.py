"""Relation (friendship) operations."""

from sqlalchemy import select
from starlette.exceptions import HTTPException

from ..models import Relation, User
from . import users


async def send(db, me: User, username: str) -> Relation:
    """Send a friend request; 400 to self, 404 unknown user, 409 if one exists."""
    other = await users.by_username(db, username)
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
    relation = Relation(from_id=me.id, to_id=other.id)
    db.add(relation)
    await db.flush()
    return relation


async def accept(db, me: User, username: str) -> Relation:
    """Accept a pending request sent to me; 404 if there is none."""
    other = await users.by_username(db, username)
    relation = await db.scalar(
        select(Relation).where(
            (Relation.from_id == other.id)
            & (Relation.to_id == me.id)
            & (Relation.status == "pending")
        )
    )
    if relation is None:
        raise HTTPException(404, f"no pending request from {username!r}")
    relation.status = "accepted"
    await db.flush()
    return relation


async def list_for(db, me: User) -> list[tuple[Relation, User]]:
    """All my relations, each paired with the user on the other end."""
    relations = (
        await db.scalars(
            select(Relation).where((Relation.from_id == me.id) | (Relation.to_id == me.id))
        )
    ).all()

    def other_id(relation: Relation) -> int:
        """The id of whoever isn't me on this edge."""
        return relation.to_id if relation.from_id == me.id else relation.from_id

    others = await users.by_ids(db, {other_id(r) for r in relations})
    return [(relation, others[other_id(relation)]) for relation in relations]
