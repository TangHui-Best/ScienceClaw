from typing import Optional
from fastapi import Request, HTTPException, Depends
from pydantic import BaseModel
from backend.config import settings
from backend.storage import get_repository


class User(BaseModel):
    id: str
    username: str
    role: str = "user"


async def get_current_user(request: Request) -> Optional[User]:
    """Dependency to get current authenticated user from session cookie."""
    if settings.storage_backend == "local":
        return User(id="local_admin", username="admin", role="admin")

    if getattr(settings, "auth_provider", "local") == "none":
        return User(id="anonymous", username="Anonymous", role="user")

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        session_id = auth.split(" ", 1)[1].strip()
    else:
        session_id = request.cookies.get(settings.session_cookie)
    if not session_id:
        return None

    repo = get_repository("user_sessions")
    session_doc = await repo.find_one({"_id": session_id})

    if not session_doc:
        return None

    import time
    if session_doc.get("expires_at", 0) < time.time():
        await repo.delete_one({"_id": session_id})
        return None

    return User(
        id=str(session_doc["user_id"]),
        username=session_doc["username"],
        role=session_doc.get("role", "user"),
    )


async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
