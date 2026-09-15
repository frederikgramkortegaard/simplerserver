"""User routes — the signature is the HTTP contract: a model-annotated
parameter is the body, the return annotation is the response shape."""

from . import Router
from .. import services
from ..db import get_db
from ..schemas import UserInput, UserOutput

router = Router()


@router.post("/users")
async def create_user(request, data: UserInput) -> UserOutput:
    user = await services.create_user(get_db(request), data)
    return UserOutput.model_validate(user, from_attributes=True)


@router.delete("/users/{id:int}")
async def delete_user(request):
    user = await services.delete_user(get_db(request), request.path_params["id"])
    return {"deleted": user.id}
