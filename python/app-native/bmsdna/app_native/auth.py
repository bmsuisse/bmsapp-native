"""Authentication hook shared by all routers.

Every `create_*_router()` requires an `auth_dependency`: a normal FastAPI
dependency that rejects the request (raise `HTTPException(401/403)`) or
returns the authenticated user. What it checks is up to you: a session
cookie, an API key, ... For the Entra ID token that the BMS app sends there
is a ready-made one, `create_entra_auth_dependency` in `entra.py`. The
return value arrives in your callbacks as `context.user`.
"""

from __future__ import annotations


async def insecure_no_auth() -> None:
    """Explicit opt-out: the endpoints accept every request.

    Only for local development, tests and the example app. Passing this to a
    router that is reachable from the internet lets anyone register devices,
    push data and act as any user.
    """
    return None
