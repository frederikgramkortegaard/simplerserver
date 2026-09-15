"""Post operations."""

from sqlalchemy import select
from starlette.exceptions import HTTPException

from ..models import Post, User
from ..schemas import PostInput, PostQuery


async def create(db, author: User, data: PostInput) -> Post:
    """Create a post owned by `author`."""
    post = Post(author_id=author.id, content=data.content)
    db.add(post)
    await db.flush()
    return post


async def search(db, query: PostQuery) -> list[Post]:
    """List posts newest-first, optionally filtered by author, paginated."""
    statement = select(Post).order_by(Post.id.desc()).limit(query.limit).offset(query.offset)
    if query.author_id is not None:
        statement = statement.where(Post.author_id == query.author_id)
    return list((await db.scalars(statement)).all())


async def delete(db, user: User, id: int) -> Post:
    """Delete a post; 404 if missing, 403 unless `user` is the author."""
    post = await db.get(Post, id)
    if post is None:
        raise HTTPException(404, f"no post {id}")
    if post.author_id != user.id:
        raise HTTPException(403, "not your post")
    await db.delete(post)
    return post
