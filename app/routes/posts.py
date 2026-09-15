"""Post routes — filtered, paginated listing with an embed flag."""

from . import Router
from .. import services
from ..auth import current_user
from ..db import get_db
from ..schemas import PostInput, PostOutput, PostQuery, UserOutput

router = Router()


@router.post("/posts")
async def create_post(request, data: PostInput) -> PostOutput:
    """Create a post authored by the authenticated user."""
    author = await current_user(request)
    post = await services.posts.create(get_db(request), author, data)
    return PostOutput.model_validate(post, from_attributes=True)


@router.get("/posts")
async def list_posts(request, query: PostQuery) -> list[PostOutput]:
    """List posts newest-first; ?author_id= filters, ?embed_author=true nests authors."""
    db = get_db(request)
    posts = await services.posts.search(db, query)
    outputs = [PostOutput.model_validate(post, from_attributes=True) for post in posts]
    if query.embed_author:
        authors = await services.users.by_ids(db, {post.author_id for post in posts})
        for output in outputs:
            author = authors[output.author_id]
            output.author = UserOutput.model_validate(author, from_attributes=True)
    return outputs


@router.delete("/posts/{id:int}")
async def delete_post(request) -> dict:
    """Delete one of the authenticated user's own posts."""
    user = await current_user(request)
    post = await services.posts.delete(get_db(request), user, request.path_params["id"])
    return {"deleted": post.id}
