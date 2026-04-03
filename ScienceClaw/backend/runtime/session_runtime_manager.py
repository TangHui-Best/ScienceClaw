from __future__ import annotations

import logging
import time

from backend.runtime.models import SessionRuntimeRecord
from backend.runtime.ownership import user_owns_runtime_session
from backend.runtime.provider import build_runtime_provider
from backend.runtime.repository import get_runtime_repository

_manager: SessionRuntimeManager | None = None
logger = logging.getLogger(__name__)


class SessionRuntimeManager:
    def __init__(self, provider=None, repository=None, settings=None, owner_checker=None):
        if settings is None:
            from backend.config import settings as default_settings

            settings = default_settings
        if provider is None:
            provider = build_runtime_provider(settings)
        self.settings = settings
        self.provider = provider
        self.repository = repository or get_runtime_repository()
        self.owner_checker = owner_checker or self._default_owner_checker

    async def _default_owner_checker(self, runtime: SessionRuntimeRecord) -> bool:
        return await user_owns_runtime_session(runtime.session_id, runtime.user_id)

    def _compute_expires_at(self, now_ts: int) -> int:
        return now_ts + int(getattr(self.settings, "runtime_idle_ttl_seconds", 3600))

    async def ensure_runtime(self, session_id: str, user_id: str):
        now_ts = int(time.time())
        existing = await self.repository.find_one({"session_id": session_id, "status": "ready"})
        if existing:
            refreshed = await self.provider.refresh_runtime(SessionRuntimeRecord(**existing))
            if refreshed.status == "missing":
                await self.repository.delete_one({"session_id": session_id})
            else:
                existing["status"] = refreshed.status
                existing["last_used_at"] = now_ts
                existing["expires_at"] = self._compute_expires_at(now_ts)
                await self.repository.update_one(
                    {"session_id": session_id},
                    {
                        "$set": {
                            "status": existing["status"],
                            "last_used_at": existing["last_used_at"],
                            "expires_at": existing["expires_at"],
                        }
                    },
                )
                return SessionRuntimeRecord(**existing)

        created = await self.provider.create_runtime(session_id, user_id)
        created_ts = max(int(created.created_at), now_ts)
        created.created_at = created_ts
        created.last_used_at = created_ts
        created.expires_at = self._compute_expires_at(created_ts)
        await self.repository.insert_one(created.model_dump())
        return created

    async def get_runtime(self, session_id: str, refresh: bool = False) -> SessionRuntimeRecord | None:
        existing = await self.repository.find_one({"session_id": session_id})
        if not existing:
            return None

        record = SessionRuntimeRecord(**existing)
        if not refresh:
            return record

        refreshed = await self.provider.refresh_runtime(record)
        if refreshed.status == "missing":
            await self.repository.delete_one({"session_id": refreshed.session_id})
            return None
        await self.repository.update_one(
            {"session_id": session_id},
            {
                "$set": {
                    "status": refreshed.status,
                }
            },
        )
        return refreshed

    async def list_runtimes(
        self,
        user_id: str | None = None,
        refresh: bool = False,
    ) -> list[SessionRuntimeRecord]:
        query = {"user_id": user_id} if user_id else {}
        records = await self.repository.find_many(query)
        runtimes = [SessionRuntimeRecord(**item) for item in records]
        if not refresh:
            return runtimes

        refreshed_records: list[SessionRuntimeRecord] = []
        for runtime in runtimes:
            refreshed = await self.provider.refresh_runtime(runtime)
            if refreshed.status == "missing":
                await self.repository.delete_one({"session_id": refreshed.session_id})
                continue
            await self.repository.update_one(
                {"session_id": refreshed.session_id},
                {
                    "$set": {
                        "status": refreshed.status,
                    }
                },
            )
            refreshed_records.append(refreshed)
        return refreshed_records

    async def destroy_runtime(self, session_id: str) -> bool:
        existing = await self.repository.find_one({"session_id": session_id})
        if not existing:
            return False

        record = SessionRuntimeRecord(**existing)
        await self.provider.delete_runtime(record)
        await self.repository.delete_one({"session_id": session_id})
        return True

    async def cleanup_orphans(self) -> int:
        records = await self.repository.find_many({})
        cleaned = 0
        for existing in records:
            record = SessionRuntimeRecord(**existing)
            if await self.owner_checker(record):
                continue
            try:
                await self.provider.delete_runtime(record)
            except Exception as exc:
                logger.warning(
                    f"Failed to delete runtime for session {record.session_id}: {exc}"
                )
                continue
            await self.repository.delete_one({"session_id": record.session_id})
            cleaned += 1
        return cleaned

    async def cleanup_expired(self, now_ts: int | None = None) -> int:
        now_ts = now_ts or int(time.time())
        records = await self.repository.find_many({})
        cleaned = 0
        for existing in records:
            expires_at = existing.get("expires_at")
            if expires_at is None or expires_at > now_ts:
                continue
            record = SessionRuntimeRecord(**existing)
            try:
                await self.provider.delete_runtime(record)
            except Exception as exc:
                logger.warning(
                    f"Failed to delete expired runtime for session {record.session_id}: {exc}"
                )
                continue
            await self.repository.delete_one({"session_id": record.session_id})
            cleaned += 1
        return cleaned


def get_session_runtime_manager(provider=None, repository=None, settings=None) -> SessionRuntimeManager:
    global _manager
    if _manager is None:
        _manager = SessionRuntimeManager(
            provider=provider,
            repository=repository,
            settings=settings,
        )
    return _manager


def reset_session_runtime_manager() -> None:
    global _manager
    _manager = None
