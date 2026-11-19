from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
import secrets
from backend.app.core.config import Settings, get_settings
from backend.app.security.auth import verify_auth_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    token: str


@router.post("/login")
def login(request: LoginRequest, response: Response, settings: Settings = Depends(get_settings)):
    expected = settings.auth_token or ""
    if not secrets.compare_digest(request.token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    response.set_cookie(
        key="chege_token",
        value=request.token,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return {"status": "authenticated"}


@router.get("/status")
def auth_status(token: str = Depends(verify_auth_token)):
    return {"status": "ok", "authenticated": True}
