"""Domain operations, one module per domain — plain async functions
with honest signatures, raising Starlette's HTTPException directly.

Usage reads like the domain: services.users.create(db, data),
services.posts.search(db, query), services.relations.send(db, me, name).
"""

from . import posts, relations, users
