import time

from pydantic import BaseModel, Field


class SessionRuntimeRecord(BaseModel):
    session_id: str
    user_id: str
    namespace: str
    pod_name: str
    service_name: str
    rest_base_url: str
    status: str
    created_at: int = Field(default_factory=lambda: int(time.time()))
    last_used_at: int = Field(default_factory=lambda: int(time.time()))
    expires_at: int | None = None
