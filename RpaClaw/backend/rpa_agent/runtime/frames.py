"""稳定 FramePath 逐层解析。"""

from __future__ import annotations

import inspect

from .locators import LocatorResolutionError, LocatorResolver
from .results import RuntimeServiceError


class FrameResolutionError(RuntimeServiceError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(phase="scope", code=code, safe_message=message)


class FrameResolver:
    def __init__(self, locators: LocatorResolver) -> None:
        self._locators = locators

    async def resolve(self, page: object, frame_path: list[object]) -> object:
        current = page
        for raw in tuple(frame_path):
            payload = raw if isinstance(raw, dict) else raw.model_dump(mode="python", exclude_none=True)
            try:
                frame_element = await self._locators.resolve_locator_specs(current, payload["locators"])
            except LocatorResolutionError as exc:
                raise FrameResolutionError("frame.not_found", "FramePath 层级无法唯一解析") from exc
            frame = getattr(frame_element, "content_frame", None)
            if callable(frame):
                frame = frame()
            if inspect.isawaitable(frame):
                frame = await frame
            if frame is None:
                raise FrameResolutionError("frame.not_found", "定位结果不是可进入的 iframe")
            current = frame
        return current
