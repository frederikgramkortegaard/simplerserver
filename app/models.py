"""The domain. Types own their invariants; the table row is the model."""

from pydantic_core import core_schema
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, validates

Base = declarative_base()


class Checked:
    """pydantic won't call arbitrary constructors without an opt-in;
    this mixin declares 'validate as the builtin, then construct me',
    so invariants stay in plain __init__."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        base = next(b for b in cls.__mro__ if b in (str, int, float, bytes))
        return core_schema.no_info_after_validator_function(cls, handler(base))


class Username(Checked, str):
    def __init__(self, value):
        if not 3 <= len(self) <= 32:
            raise ValueError(f"invalid username: {value!r}")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    age: Mapped[int]

    @validates("username")
    def _validate_username(self, key, value):
        return Username(value)  # the type still owns the invariant
