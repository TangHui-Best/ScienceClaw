"""Browser-use 0.13.2 invocation boundary.

Private DOM indexes, tab ids, and managed file paths are consumed here and are
never allowed to enter the creation-state contracts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


class BrowserUseInvocationNormalizer:
    def __init__(
        self,
        *,
        page_registry: object,
        tab_runtime_resolver: Callable[[str], str],
        main_frame_resolver: Callable[[str], str],
        asset_ref_resolver: Callable[[str], str],
        frame_path_resolver: Callable[[str, str], Sequence[Mapping[str, Any]]],
    ) -> None:
        self._page_registry = page_registry
        self._tab_runtime_resolver = tab_runtime_resolver
        self._main_frame_resolver = main_frame_resolver
        self._asset_ref_resolver = asset_ref_resolver
        self._frame_path_resolver = frame_path_resolver

    @staticmethod
    def _parameters(params: object) -> dict[str, Any]:
        if isinstance(params, Mapping):
            return dict(params)
        model_dump = getattr(params, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(mode="python", exclude_none=True)
            if isinstance(dumped, Mapping):
                return dict(dumped)
        raise TypeError("browser_use_invocation.params_invalid")

    def normalize(
        self,
        action_name: str,
        params: object,
        *,
        candidate_id: str,
        business_intent: str,
        source_page_runtime_ref: str,
        source_frame_runtime_ref: str,
        binding_hints: Sequence[Mapping[str, Any]] = (),
        target_hint: Mapping[str, Any] | None = None,
        business_required: bool = True,
    ):
        # Local import deliberately prevents a module cycle: the DTO is the
        # adapter's public boundary, while this module only builds it.
        from .adapter import ActualToolAction

        data = self._parameters(params)
        runtime_page_ref = source_page_runtime_ref
        runtime_frame_ref = source_frame_runtime_ref
        page_ref = self._page_registry.resolve(runtime_page_ref)
        source_index = data.get("index")
        if not isinstance(source_index, int) or isinstance(source_index, bool):
            source_index = None
        normalized: dict[str, Any]

        if action_name == "select_dropdown":
            normalized = {"option": data.get("text")}
        elif action_name == "scroll":
            pages = data.get("pages", 1.0)
            normalized = {
                "direction": "down" if data.get("down", True) else "up",
                "business_required": business_required,
            }
            if (
                isinstance(pages, (int, float))
                and not isinstance(pages, bool)
                and pages >= 1
                and float(pages).is_integer()
            ):
                normalized.update({"amount": int(pages), "unit": "viewport"})
            else:
                normalized["pages"] = pages
        elif action_name == "switch":
            target_runtime_ref = self._tab_runtime_resolver(str(data["tab_id"]))
            normalized = {"page_ref": self._page_registry.resolve(target_runtime_ref)}
        elif action_name == "close":
            runtime_page_ref = self._tab_runtime_resolver(str(data["tab_id"]))
            runtime_frame_ref = self._main_frame_resolver(runtime_page_ref)
            page_ref = self._page_registry.resolve(runtime_page_ref)
            normalized = {}
        elif action_name == "upload_file":
            normalized = {"asset_ref": self._asset_ref_resolver(str(data["path"]))}
        elif action_name == "input":
            normalized = {"text": data.get("text"), "clear": data.get("clear", True)}
        elif action_name == "click":
            normalized = {
                key: data[key]
                for key in ("coordinate_x", "coordinate_y")
                if data.get(key) is not None
            }
        elif action_name == "navigate":
            normalized = {"url": data.get("url")}
            if data.get("new_tab") is not None:
                normalized["new_tab"] = data["new_tab"]
        elif action_name == "send_keys":
            normalized = {"keys": data.get("keys")}
        elif action_name == "extract":
            normalized = {
                key: data[key]
                for key in ("mode", "attribute", "columns")
                if key in data
            }
        else:
            # The allow/deny gate in the adapter owns execution authority.  For
            # explicitly enabled extensions we still remove known private keys.
            normalized = {
                key: value
                for key, value in data.items()
                if key not in {"index", "tab_id", "path", "file_path"}
            }

        frame_path = tuple(
            self._frame_path_resolver(runtime_page_ref, runtime_frame_ref)
        )
        return ActualToolAction(
            action_name=action_name,
            candidate_id=candidate_id,
            params=normalized,
            business_intent=business_intent,
            runtime_page_ref=runtime_page_ref,
            runtime_frame_ref=runtime_frame_ref,
            page_ref=page_ref,
            frame_path=frame_path,
            target_hint=target_hint,
            binding_hints=tuple(binding_hints),
            source_index=source_index,
        )
