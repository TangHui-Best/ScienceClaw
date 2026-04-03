from __future__ import annotations

import time

from backend.runtime.models import SessionRuntimeRecord


class SharedRuntimeProvider:
    def __init__(self, settings):
        self.settings = settings

    async def create_runtime(self, session_id: str, user_id: str) -> SessionRuntimeRecord:
        rest_base_url = getattr(self.settings, "shared_sandbox_rest_url", "http://sandbox:8080")
        now = int(time.time())
        return SessionRuntimeRecord(
            session_id=session_id,
            user_id=user_id,
            namespace=getattr(self.settings, "k8s_namespace", "local"),
            pod_name="shared-sandbox",
            service_name="shared-sandbox",
            rest_base_url=rest_base_url.rstrip("/"),
            status="ready",
            created_at=now,
            last_used_at=now,
        )

    async def delete_runtime(self, runtime_record) -> None:
        return None

    async def refresh_runtime(self, runtime_record):
        return runtime_record
