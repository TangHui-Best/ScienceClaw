from __future__ import annotations

import re
from typing import Any, Dict, Optional


class LocatorCompileError(ValueError):
    pass


_RANDOM_ID_RE = re.compile(
    r"#[-_a-zA-Z]*(?:\d{4,}|[0-9a-f]{8,})(?:[-_a-zA-Z0-9]*)?$"
)
_BROAD_HREF_RE = re.compile(r"\bhref\s*\*=")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _css_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def is_stable_locator_payload(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False

    method = payload.get("method")
    if method is None and payload.get("role"):
        method = "role"
    if method in {"role", "label", "placeholder", "alt", "title", "text", "testid"}:
        return bool(_clean_text(payload.get("name") or payload.get("value") or payload.get("role")))

    if method == "nested":
        return is_stable_locator_payload(payload.get("parent") or {}) and is_stable_locator_payload(
            payload.get("child") or {}
        )

    if method != "css":
        return False

    value = _clean_text(payload.get("value"))
    if not value:
        return False
    if _BROAD_HREF_RE.search(value):
        return False
    if _RANDOM_ID_RE.search(value):
        return False
    return True


class LocatorCompiler:
    def compile_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(node, dict):
            raise LocatorCompileError("node must be a dictionary")

        href_locator = self._compile_exact_href(node)
        if href_locator:
            return href_locator

        role_locator = self._compile_role_name(node)
        if role_locator:
            return role_locator

        existing_locator = node.get("locator")
        if isinstance(existing_locator, dict) and is_stable_locator_payload(existing_locator):
            return dict(existing_locator)

        raise LocatorCompileError("no stable locator can be compiled")

    def compile_scoped(
        self,
        parent: Dict[str, Any],
        child: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not is_stable_locator_payload(parent):
            raise LocatorCompileError("parent locator is not stable")
        if not is_stable_locator_payload(child):
            raise LocatorCompileError("child locator is not stable")
        return {"method": "nested", "parent": dict(parent), "child": dict(child)}

    @staticmethod
    def _compile_exact_href(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        href = _clean_text(node.get("href"))
        if not href or href.startswith("#"):
            return None
        if node.get("role") != "link":
            return None
        return {"method": "css", "value": f'a[href="{_css_quote(href)}"]'}

    @staticmethod
    def _compile_role_name(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        role = _clean_text(node.get("role"))
        name = _clean_text(node.get("name"))
        if not role or not name:
            return None
        return {"method": "role", "role": role, "name": name, "exact": False}
