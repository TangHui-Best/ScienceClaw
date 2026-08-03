"""vNext browser-host factory backed by a lease-owned Docker runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence

from ..host import BrowserHostSession, PlaywrightBrowserSessionPort, new_host_identity
from .runtime_provider import RuntimeLease, RuntimeLeaseError


class DockerBrowserHostFactory:
    """Create fresh Playwright contexts from only the supplied vNext lease."""

    def __init__(
        self,
        *,
        resolve_cdp_url: Callable[[RuntimeLease], Awaitable[str]],
        preview_registry: object,
        acquire_runtime_lease: Callable[..., Awaitable[object]],
    ) -> None:
        self._resolve_cdp_url = resolve_cdp_url
        self._preview_registry = preview_registry
        self._acquire_runtime_lease = acquire_runtime_lease

    async def create_recording(
        self, *, owner_id: str, lease: RuntimeLease
    ) -> BrowserHostSession:
        return await self._create(owner_id=owner_id, lease=lease, prefix="recording")

    async def create_replay(
        self, *, owner_id: str, lease: RuntimeLease, skill_id: str
    ) -> BrowserHostSession:
        del skill_id
        return await self._create(owner_id=owner_id, lease=lease, prefix="replay")

    async def _create(
        self, *, owner_id: str, lease: RuntimeLease, prefix: str
    ) -> BrowserHostSession:
        if lease.user_id != owner_id:
            raise RuntimeLeaseError("runtime_lease_owner_conflict")
        browser_ref, generation = new_host_identity("rpa_agent_next_" + prefix)
        cdp_url = await self._resolve_cdp_url(lease)
        browser_lease = await self._acquire_runtime_lease(
            owner_id=owner_id,
            browser_ref=browser_ref,
            preview_registry=self._preview_registry,
            resolve_cdp_url=lambda _ref, _owner: _resolved(cdp_url),
        )
        try:
            port = _port_from_browser_lease(browser_lease)
        except BaseException:
            await browser_lease.aclose()
            raise
        return BrowserHostSession(
            browser_session_ref=browser_ref,
            page_ref=port.main_page_runtime_ref,
            target_id=port.main_page_runtime_ref,
            generation=generation,
            port=port,
        )


async def _resolved(value: str) -> str:
    return value


def _port_from_browser_lease(browser_lease: object) -> PlaywrightBrowserSessionPort:
    page = getattr(browser_lease, "page", None)
    if page is None:
        raise RuntimeError("rpa_agent_next.browser_page_unavailable")
    context = getattr(page, "context", None)
    main_frame = getattr(page, "main_frame", None)
    if context is None or main_frame is None:
        raise RuntimeError("rpa_agent_next.browser_context_unavailable")

    page_refs: dict[int, str] = {}
    pages_by_ref: dict[str, object] = {}
    frame_refs: dict[int, str] = {}
    frames_by_ref: dict[str, object] = {}

    def page_runtime_ref(target: object) -> str:
        key = id(target)
        if key not in page_refs:
            page_refs[key] = f"next_page_{len(page_refs) + 1:04d}"
        runtime_ref = page_refs[key]
        pages_by_ref[runtime_ref] = target
        return runtime_ref

    def frame_runtime_ref(target: object) -> str:
        key = id(target)
        if key not in frame_refs:
            frame_refs[key] = f"next_frame_{len(frame_refs) + 1:04d}"
        runtime_ref = frame_refs[key]
        frames_by_ref[runtime_ref] = target
        return runtime_ref

    def frame_path(page_ref: str, frame_ref: str) -> Sequence[Mapping[str, object]]:
        target_page = pages_by_ref.get(page_ref)
        target_frame = frames_by_ref.get(frame_ref)
        if target_page is None or target_frame is None:
            raise ValueError("rpa_agent_next.frame_not_registered")
        root = getattr(target_page, "main_frame", None)
        if root is None:
            raise ValueError("rpa_agent_next.main_frame_unavailable")
        if target_frame is root:
            return ()
        reversed_steps: list[Mapping[str, object]] = []
        current = target_frame
        while current is not root:
            parent = getattr(current, "parent_frame", None)
            name = getattr(current, "name", None)
            if parent is None or not isinstance(name, str) or not name:
                raise ValueError("rpa_agent_next.frame_path_unavailable")
            reversed_steps.append(
                {
                    "name": name,
                    "locators": [
                        {"strategy": "css", "value": 'iframe[name="' + name + '"]'}
                    ],
                }
            )
            current = parent
        return tuple(reversed(reversed_steps))

    main_page_ref = page_runtime_ref(page)
    main_frame_ref = frame_runtime_ref(main_frame)
    return PlaywrightBrowserSessionPort(
        context=context,
        main_page=page,
        main_page_runtime_ref=main_page_ref,
        main_frame_runtime_ref=main_frame_ref,
        page_runtime_ref=page_runtime_ref,
        frame_runtime_ref=frame_runtime_ref,
        frame_path=frame_path,
        page_main_frame_runtime_ref=lambda target: frame_runtime_ref(
            getattr(target, "main_frame")
        ),
        browser_use_cdp_url=getattr(browser_lease, "cdp_url", None),
        cleanup=browser_lease.aclose,
    )


__all__ = ["DockerBrowserHostFactory"]
