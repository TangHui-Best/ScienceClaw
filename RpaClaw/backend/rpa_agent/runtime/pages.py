"""显式逻辑 PageRef 生命周期。"""

from __future__ import annotations

from .results import RuntimeServiceError


class PageRegistryError(RuntimeServiceError):
    def __init__(self, value: str) -> None:
        code = value.split(":", 1)[0]
        super().__init__(phase="scope", code=code, safe_message="PageRef 生命周期校验失败")


class PageRegistry:
    def __init__(self, main_page: object) -> None:
        if main_page is None:
            raise PageRegistryError("page.main_required")
        self._pages: dict[str, object] = {"main": main_page}
        self._closed: set[str] = set()
        self._active_ref: str | None = "main"

    @property
    def active_ref(self) -> str | None:
        return self._active_ref

    def require(self, page_ref: str) -> object:
        if page_ref in self._closed:
            raise PageRegistryError(f"page.closed:{page_ref}")
        if page_ref not in self._pages:
            raise PageRegistryError(f"page.unknown:{page_ref}")
        return self._pages[page_ref]

    def register(self, page_ref: str, page: object) -> object:
        if page_ref in self._pages or page_ref in self._closed:
            raise PageRegistryError(f"page.duplicate:{page_ref}")
        self._pages[page_ref] = page
        return page

    def activate(self, page_ref: str) -> object:
        page = self.require(page_ref)
        self._active_ref = page_ref
        return page

    async def close(self, page_ref: str) -> None:
        page = self.require(page_ref)
        await page.close()
        self._closed.add(page_ref)
        if self._active_ref == page_ref:
            self._active_ref = None
