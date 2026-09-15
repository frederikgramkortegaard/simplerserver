"""Relation routes — friend requests: send, accept, list."""

from . import Router
from .. import services
from ..auth import current_user
from ..db import get_db
from ..schemas import RelationOutput

router = Router()


@router.post("/relations/{username}")
async def send_request(request) -> RelationOutput:
    """Send a friend request to `username`."""
    me = await current_user(request)
    username = request.path_params["username"]
    await services.relations.send(get_db(request), me, username)
    return RelationOutput(username=username, status="pending_sent")


@router.post("/relations/{username}/accept")
async def accept_request(request) -> RelationOutput:
    """Accept the pending friend request from `username`."""
    me = await current_user(request)
    username = request.path_params["username"]
    await services.relations.accept(get_db(request), me, username)
    return RelationOutput(username=username, status="friends")


@router.get("/relations")
async def list_relations(request) -> list[RelationOutput]:
    """All of the authenticated user's relations, seen from their side."""
    me = await current_user(request)
    pairs = await services.relations.list_for(get_db(request), me)
    outputs = []
    for relation, other in pairs:
        if relation.status == "accepted":
            status = "friends"
        elif relation.from_id == me.id:
            status = "pending_sent"
        else:
            status = "pending_received"
        outputs.append(RelationOutput(username=other.username, status=status))
    return outputs
