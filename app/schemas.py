"""The DTOs — what crosses the HTTP boundary.

Inputs forbid extra fields (declared fields are the whitelist); outputs
can never leak a column they don't name. Query models are the same idea
for GET parameters.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import Content, Email, Limit, Offset, Username


# -- users ----------------------------------------------------------------

class UserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Username
    email: Email
    full_name: str


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email | None = None
    full_name: str | None = None


class SignupOutput(BaseModel):
    id: int
    username: Username
    email: Email
    full_name: str
    api_token: str  # only ever returned once, at signup


class MeOutput(BaseModel):
    id: int
    username: Username
    email: Email
    full_name: str


class UserOutput(BaseModel):
    """The public shape of a user — no email, no token."""

    id: int
    username: Username
    full_name: str


# -- posts ------------------------------------------------------------------

class PostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Content


class PostQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author_id: int | None = None
    limit: Limit = Limit(20)
    offset: Offset = Offset(0)
    embed_author: bool = False


class PostOutput(BaseModel):
    id: int
    author_id: int
    content: Content
    created_at: datetime
    author: UserOutput | None = None  # filled when ?embed_author=true


# -- relations ---------------------------------------------------------------

class RelationOutput(BaseModel):
    username: Username
    status: str  # pending_sent | pending_received | friends
