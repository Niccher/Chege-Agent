from fastapi import Depends, HTTPException, Header, Query, Request, status
import secrets
from backend.app.core.config import Settings, get_settings


def verify_auth_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_chege_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    Verify incoming request token against the configured server secret (SEC-03).
    Supports:
    - Authorization: Bearer <token>
    - X-Chege-Token: <token>
    - Query parameter ?token=<token> (useful for EventSource and WebSockets)
    - Session cookie: chege_token
    """
    if not settings.auth_enabled:
        return "anonymous"

    provided_token: str | None = None

    if authorization and authorization.lower().startswith("bearer "):
        provided_token = authorization[7:].strip()
    elif x_chege_token:
        provided_token = x_chege_token.strip()
    elif token:
        provided_token = token.strip()
    elif "chege_token" in request.cookies:
        provided_token = request.cookies["chege_token"]

    if not provided_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide Bearer token or cookie.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expected_token = settings.auth_token or ""
    if not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication token.",
        )

    return provided_token
