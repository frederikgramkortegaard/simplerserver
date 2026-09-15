"""The domain. Types own their invariants; the table rows are the models."""

from datetime import UTC, datetime

from pydantic_core import core_schema
from sqlalchemy import ForeignKey, UniqueConstraint
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


class Email(Checked, str):
    def __init__(self, value):
        if "@" not in self or len(self) > 254:
            raise ValueError(f"invalid email: {value!r}")


class Content(Checked, str):
    def __init__(self, value):
        if not 1 <= len(self) <= 500:
            raise ValueError("post content must be 1-500 characters")


class Limit(Checked, int):
    def __init__(self, value):
        if not 1 <= self <= 100:
            raise ValueError(f"limit must be between 1 and 100, got {self}")


class Offset(Checked, int):
    def __init__(self, value):
        if self < 0:
            raise ValueError(f"offset must be >= 0, got {self}")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(unique=True)
    full_name: Mapped[str]
    api_token: Mapped[str] = mapped_column(unique=True)

    @validates("username")
    def _validate_username(self, key, value) -> Username:
        """Every write to `username` goes through the type."""
        return Username(value)

    @validates("email")
    def _validate_email(self, key, value) -> Email:
        """Every write to `email` goes through the type."""
        return Email(value)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    @validates("content")
    def _validate_content(self, key, value) -> Content:
        """Every write to `content` goes through the type."""
        return Content(value)


class Relation(Base):
    """A friendship edge: pending until the addressee accepts."""

    __tablename__ = "relations"
    __table_args__ = (UniqueConstraint("from_id", "to_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    to_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(default="pending")
