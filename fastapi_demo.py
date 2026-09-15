"""The same app as demo.py, written the canonical FastAPI way —
Annotated, Depends, Pydantic, response_model. Same behavior, same
database shape; compare the plumbing.

(Named fastapi_demo.py because a file called fastapi.py would shadow
the real fastapi package and break its own imports.)

Run:  .venv/bin/python fastapi_demo.py           walkthrough
      .venv/bin/python fastapi_demo.py --serve   uvicorn on :8000
"""

import json
import pathlib
import sys
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# ---------------------------------------------------------------- types
# Not a type — an alias carrying metadata for frameworks to interpret.
Username = Annotated[str, Field(min_length=3, max_length=32)]


# --------------------------------------------------------------- models
class UserInput(BaseModel):
    username: Username
    age: int


class UserOut(BaseModel):
    id: int
    username: Username
    age: int
    model_config = {"from_attributes": True}  # allow returning ORM rows


class UserRef(BaseModel):
    # delete_user can't take the SQLAlchemy User as a body param,
    # so a third schema class exists just to carry the id.
    id: int


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    age: Mapped[int]


engine = create_engine(
    "sqlite:///fastapi_demo.db", connect_args={"check_same_thread": False}
)


# --------------------------------------------------------- dependencies
def get_db():
    db = Session(engine)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ------------------------------------------------------------ endpoints
app = FastAPI()


@app.post("/users", response_model=UserOut)
def create_user(user: UserInput, db: Annotated[Session, Depends(get_db)]):
    if db.scalar(select(User).where(User.username == user.username)) is not None:
        raise HTTPException(409, f"username {user.username!r} is taken")
    row = User(username=user.username, age=user.age)
    db.add(row)
    db.flush()
    return row


@app.delete("/users")
def delete_user(user: UserRef, db: Annotated[Session, Depends(get_db)]):
    row = db.get(User, user.id)
    if row is None:
        raise HTTPException(404, f"no user {user.id}")
    db.delete(row)
    return {"deleted": user.id}


# ------------------------------------------------------------ walkthrough
def main():
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)

    def call(method, path, body=None):
        suffix = f"  {json.dumps(body)}" if body is not None else ""
        print(f"  {method} {path}{suffix}")
        response = client.request(method, path, json=body)
        print(f"      -> {response.status_code} {response.text}")

    print("== the 'type' cannot validate itself ==")
    print("  Username('x') is impossible — Username is not a class.")
    try:
        TypeAdapter(Username).validate_python("x")  # the pydantic incantation
    except Exception as exc:
        first_line = str(exc).splitlines()[1].strip()
        print(f"  TypeAdapter(Username).validate_python('x')  !!  {first_line}")

    print("\n== create_user(user: UserInput) ==")
    call("POST", "/users", {"username": "frederik", "age": 27})
    call("POST", "/users", {"username": "bob", "age": 34})
    call("POST", "/users", {"username": "frederik", "age": 30})
    call("POST", "/users", {"username": "x", "age": 27})
    call("POST", "/users", {"username": "frederik"})

    print("\n== delete_user(user: UserRef) ==")
    call("DELETE", "/users", {"id": 1})
    call("DELETE", "/users", {"id": 1})
    print()


if __name__ == "__main__":
    pathlib.Path("fastapi_demo.db").unlink(missing_ok=True)
    Base.metadata.create_all(engine)
    if "--serve" in sys.argv:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        main()
