"""Owned browser hosts for recording, test replay, and production runs."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Protocol, runtime_checkable

from .browser_session import BrowserSessionPort


@dataclass(slots=True)
class BrowserHostSession:
    browser_session_ref: str
    page_ref: str
    target_id: str
    generation: str
    port: BrowserSessionPort
    _closed: bool = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        cleanup = getattr(self.port, "aclose", None)
        if callable(cleanup):
            await cleanup()


@runtime_checkable
class BrowserRunSessionFactory(Protocol):
    async def create_recording(self, *, owner_id: str) -> BrowserHostSession: ...

    async def create_test(
        self, *, owner_id: str, skill_id: str
    ) -> BrowserHostSession: ...

    async def create_run(
        self, *, owner_id: str, skill_id: str
    ) -> BrowserHostSession: ...


def new_host_identity(prefix: str) -> tuple[str, str]:
    return (
        f"{prefix}_" + secrets.token_hex(12),
        "gen_" + secrets.token_hex(12),
    )


__all__ = [
    "BrowserHostSession",
    "BrowserRunSessionFactory",
    "new_host_identity",
]
