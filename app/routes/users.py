"""User routes — signup and the authenticated /me pair."""

from . import Router
from .. import services
from ..auth import current_user
from ..db import get_db
from ..schemas import MeOutput, SignupOutput, UserInput, UserUpdate

router = Router()


@router.post("/users")
async def signup(request, data: UserInput) -> SignupOutput:
    """Create an account; the response includes the api token, once."""
    user = await services.users.create(get_db(request), data)
    return SignupOutput.model_validate(user, from_attributes=True)


@router.get("/me")
async def me(request) -> MeOutput:
    """The authenticated user's own profile."""
    user = await current_user(request)
    return MeOutput.model_validate(user, from_attributes=True)


@router.patch("/me")
async def update_me(request, data: UserUpdate) -> MeOutput:
    """Partially update the authenticated user's profile."""
    user = await current_user(request)
    user = await services.users.update(get_db(request), user, data)
    return MeOutput.model_validate(user, from_attributes=True)
