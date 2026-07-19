from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

import pytest

from backend.rpa_agent.host.browser_session import (
    HostBrowserEvent,
    PlaywrightBrowserSessionPort,
)
from backend.rpa_agent.host.manual_input import ManualInputPort


class _Handle:
    def __init__(self, element: "_Element | None") -> None:
        self._element = element

    def as_element(self) -> "_Element | None":
        return self._element


class _Locator:
    def __init__(self, matches: list["_Element"]) -> None:
        self._matches = matches

    async def count(self) -> int:
        return len(self._matches)

    async def element_handle(self) -> "_Element | None":
        return self._matches[0] if len(self._matches) == 1 else None


class _Element:
    def __init__(
        self,
        snapshot: dict[str, object],
        *,
        content_frame: "_Frame | None" = None,
        box: dict[str, float] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.control: _Element | None = None
        self._content_frame = content_frame
        self._box = box
        self.click_count = 0
        self.value = str(snapshot.get("value", ""))
        self.checked = bool(snapshot.get("checked", False))

    async def evaluate_handle(self, _expression: str) -> _Handle:
        return _Handle(self.control or self)

    async def evaluate(self, expression: str, arg: object | None = None) -> object:
        if arg is not None:
            return self is arg
        if "getBoundingClientRect" in expression:
            return self._box
        if "Boolean(node.checked)" in expression and "const tag" not in expression:
            return self.checked
        if "String(node.value" in expression:
            return self.value
        return dict(self.snapshot)

    async def content_frame(self) -> "_Frame | None":
        return self._content_frame

    async def bounding_box(self) -> dict[str, float] | None:
        return self._box

    async def click(self) -> None:
        self.click_count += 1

    async def press_sequentially(self, text: str) -> None:
        self.value += text


class _Frame:
    def __init__(
        self,
        ref: str,
        *,
        parent_frame: "_Frame | None" = None,
        name: str = "",
    ) -> None:
        self.ref = ref
        self.parent_frame = parent_frame
        self.name = name
        self.url = f"https://eval.invalid/{ref}"
        self.page: _Page | None = None
        self.point_element: _Element | None = None
        self.active_element: _Element | None = None
        self.frame_element_value: _Element | None = None
        self.matches: dict[tuple[object, ...], list[_Element]] = {}

    async def evaluate_handle(self, expression: str, _arg: object = None) -> _Handle:
        if "activeElement" in expression:
            return _Handle(self.active_element)
        return _Handle(self.point_element)

    async def frame_element(self) -> _Element:
        assert self.frame_element_value is not None
        return self.frame_element_value

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = True) -> _Locator:
        return _Locator(self.matches.get(("role", role, name, exact), []))

    def get_by_test_id(self, value: str) -> _Locator:
        return _Locator(self.matches.get(("test_id", value), []))

    def get_by_label(self, value: str, *, exact: bool = True) -> _Locator:
        return _Locator(self.matches.get(("label", value, exact), []))

    def get_by_placeholder(self, value: str, *, exact: bool = True) -> _Locator:
        return _Locator(self.matches.get(("placeholder", value, exact), []))

    def get_by_text(self, value: str, *, exact: bool = True) -> _Locator:
        return _Locator(self.matches.get(("text", value, exact), []))

    def get_by_title(self, value: str, *, exact: bool = True) -> _Locator:
        return _Locator(self.matches.get(("title", value, exact), []))

    def get_by_alt_text(self, value: str, *, exact: bool = True) -> _Locator:
        return _Locator(self.matches.get(("alt_text", value, exact), []))

    def locator(self, value: str) -> _Locator:
        return _Locator(self.matches.get(("css", value), []))


class _Page:
    def __init__(self, ref: str, main_frame: _Frame) -> None:
        self.ref = ref
        self.url = f"https://eval.invalid/{ref}"
        self.main_frame = main_frame
        self.frames = [main_frame]
        main_frame.page = self
        self.listeners: dict[str, list[Callable[[object], None]]] = defaultdict(list)

    def on(self, event: str, callback: Callable[[object], None]) -> None:
        self.listeners[event].append(callback)

    def remove_listener(self, event: str, callback: Callable[[object], None]) -> None:
        self.listeners[event].remove(callback)

    def emit(self, event: str, value: object) -> None:
        for callback in tuple(self.listeners[event]):
            callback(value)


class _Context:
    def __init__(self, page: _Page) -> None:
        self.pages = [page]


def _port(page: _Page) -> PlaywrightBrowserSessionPort:
    return PlaywrightBrowserSessionPort(
        context=_Context(page),
        main_page=page,
        main_page_runtime_ref=page.ref,
        main_frame_runtime_ref=page.main_frame.ref,
        page_runtime_ref=lambda value: value.ref,
        frame_runtime_ref=lambda value: value.ref,
        frame_path=lambda _page, _frame: (),
        page_main_frame_runtime_ref=lambda value: value.main_frame.ref,
        active_page=lambda: page,
    )


@pytest.mark.asyncio
async def test_pointer_target_keeps_only_unique_stable_locator() -> None:
    frame = _Frame("frame_main")
    page = _Page("runtime_main", frame)
    button = _Element(
        {
            "tag": "button",
            "role": "button",
            "text": "Query",
            "aria_label": "",
            "label": "",
            "placeholder": "",
            "title": "",
            "alt": "",
            "test_id": "",
            "name_attr": "",
            "input_type": "",
            "editable": False,
            "checked": False,
        }
    )
    frame.point_element = button
    frame.matches[("role", "button", "Query", True)] = [button]
    port = _port(page)

    target = await port.resolve_pointer_target(x=10, y=20)

    assert isinstance(port, ManualInputPort)
    assert target.interaction_kind == "click"
    assert target.page_runtime_ref == "runtime_main"
    assert target.frame_runtime_ref == "frame_main"
    assert target.target_locators == (
        {"strategy": "role", "role": "button", "name": "Query", "exact": True},
    )


@pytest.mark.asyncio
async def test_pointer_target_fails_closed_when_all_locators_are_ambiguous() -> None:
    frame = _Frame("frame_main")
    page = _Page("runtime_main", frame)
    button = _Element(
        {
            "tag": "button",
            "role": "button",
            "text": "Start acceptance",
            "aria_label": "",
            "label": "",
            "placeholder": "",
            "title": "",
            "alt": "",
            "test_id": "",
            "name_attr": "",
            "input_type": "",
            "editable": False,
            "checked": False,
        }
    )
    twin = _Element(dict(button.snapshot))
    frame.point_element = button
    frame.matches[("role", "button", "Start acceptance", True)] = [button, twin]
    frame.matches[("text", "Start acceptance", True)] = [button, twin]
    port = _port(page)

    with pytest.raises(ValueError, match="manual_input.target_locator_unavailable"):
        await port.resolve_pointer_target(x=10, y=20)


@pytest.mark.asyncio
async def test_iframe_target_has_unique_frame_path_and_popup_uses_exact_source_frame() -> None:
    main_frame = _Frame("frame_main")
    page = _Page("runtime_main", main_frame)
    child = _Frame("frame_acceptance", parent_frame=main_frame, name="acceptance-frame")
    child.page = page
    page.frames.append(child)
    iframe = _Element(
        {
            "tag": "iframe",
            "role": "",
            "text": "",
            "aria_label": "",
            "label": "",
            "placeholder": "",
            "title": "",
            "alt": "",
            "test_id": "",
            "name_attr": "acceptance-frame",
            "input_type": "",
            "editable": False,
            "checked": False,
        },
        content_frame=child,
        box={"x": 100, "y": 50, "width": 500, "height": 400},
    )
    child.frame_element_value = iframe
    field = _Element(
        {
            "tag": "input",
            "role": "textbox",
            "text": "",
            "aria_label": "",
            "label": "Order number",
            "placeholder": "",
            "title": "",
            "alt": "",
            "test_id": "",
            "name_attr": "",
            "input_type": "text",
            "editable": True,
            "checked": False,
        }
    )
    main_frame.point_element = iframe
    child.point_element = field
    main_frame.matches[("css", 'iframe[name="acceptance-frame"]')] = [iframe]
    child.matches[("role", "textbox", "Order number", True)] = [field]
    child.matches[("label", "Order number", True)] = [field]
    port = _port(page)
    target = await port.resolve_pointer_target(x=120, y=80)

    assert target.interaction_kind == "fill"
    assert port.resolve_frame_path("runtime_main", "frame_acceptance") == (
        {
            "name": "acceptance-frame",
            "locators": [
                {"strategy": "css", "value": 'iframe[name="acceptance-frame"]'},
            ],
        },
    )

    popup_frame = _Frame("frame_popup")
    popup = _Page("runtime_popup", popup_frame)
    events: list[HostBrowserEvent] = []
    port.subscribe("new_page", events.append)
    async with port.action_dispatch_scope(target):
        page.emit("popup", popup)

    assert events[0].source_page_runtime_ref == "runtime_main"
    assert events[0].source_frame_runtime_ref == "frame_acceptance"
