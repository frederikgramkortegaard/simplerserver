"""The DTOs — what crosses the HTTP boundary, in and out.

Declared fields are the whitelist: extra="forbid" makes mass assignment
impossible, and UserOutput can never leak a column it doesn't name.
"""

from pydantic import BaseModel, ConfigDict

from .models import Username


class UserInput(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    username: Username
    age: int


class UserOutput(BaseModel):
    id: int
    username: Username
    age: int
