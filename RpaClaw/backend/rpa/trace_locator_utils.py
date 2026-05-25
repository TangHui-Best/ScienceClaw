from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_VALUE_METHODS = {"text", "testid", "label", "placeholder", "alt", "title", "css"}
_DATA_TEST_ATTR_RE = re.compile(
    r"\[\s*(?:data-testid|data-test-id|data-test)\s*=\s*['\"]?([^'\"\]\s]+)",
    re.IGNORECASE,
)
_CSS_ID_TOKEN_RE = re.compile(r"#([A-Za-z_][\w:-]*)")
_CSS_CLASS_TOKEN_RE = re.compile(r"\.([A-Za-z_][\w:-]*)")


def normalize_locator(locator: Any) -> Dict[str, Any]:
    if not isinstance(locator, dict):
        return {}

    method = str(locator.get("method") or "").strip()
    if not method and locator.get("role"):
        method = "role"
    if not method and isinstance(locator.get("value"), str) and locator.get("value").strip():
        method = "css"
    if not method:
        return {}

    normalized: Dict[str, Any] = {"method": method}

    if method == "role":
        role = str(locator.get("role") or "").strip()
        if not role:
            return {}
        normalized["role"] = role
        if isinstance(locator.get("name"), str) and locator.get("name").strip():
            normalized["name"] = locator["name"].strip()
        if locator.get("exact") is not None:
            normalized["exact"] = bool(locator.get("exact"))
        return normalized

    if method in _VALUE_METHODS:
        value = str(locator.get("value") or "").strip()
        if not value:
            return {}
        normalized["value"] = value
        if locator.get("exact") is not None:
            normalized["exact"] = bool(locator.get("exact"))
        return normalized

    if method == "nested":
        parent = normalize_locator(locator.get("parent"))
        child = normalize_locator(locator.get("child"))
        if not parent or not child:
            return {}
        normalized["parent"] = parent
        normalized["child"] = child
        return normalized

    if method == "nth":
        base = normalize_locator(locator.get("locator") or locator.get("base"))
        if not base:
            return {}
        try:
            index = int(locator.get("index") or 0)
        except Exception:
            return {}
        normalized["locator"] = base
        normalized["index"] = max(index, 0)
        return normalized

    return {}


def normalize_locator_candidates(
    candidates: Any,
    *,
    target: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    normalized_candidates: List[Dict[str, Any]] = []
    target = normalize_locator(target or {})
    target_key = repr(target) if target else ""

    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            locator = normalize_locator(candidate.get("locator") if "locator" in candidate else candidate)
            if not locator:
                continue
            item = dict(candidate)
            item["locator"] = locator
            normalized_candidates.append(item)

    selected_index = next(
        (index for index, candidate in enumerate(normalized_candidates) if candidate.get("selected")),
        None,
    )
    if selected_index is None and target_key:
        selected_index = next(
            (
                index
                for index, candidate in enumerate(normalized_candidates)
                if repr(candidate.get("locator")) == target_key
            ),
            None,
        )

    if normalized_candidates and target:
        if selected_index is None:
            selected_index = 0
        normalized_candidates[selected_index]["locator"] = target
    elif selected_index is None and target:
        normalized_candidates.insert(0, {"locator": target, "selected": True})
        selected_index = 0

    if normalized_candidates and selected_index is None:
        selected_index = 0

    for index, candidate in enumerate(normalized_candidates):
        candidate["selected"] = index == selected_index

    return normalized_candidates


def has_valid_locator(locator: Any) -> bool:
    return bool(normalize_locator(locator))


def locator_instability_penalty(
    locator: Any,
    *,
    extra_values: Optional[List[Any]] = None,
) -> float:
    normalized = normalize_locator(locator)
    penalty = _locator_instability_penalty(normalized)
    for value in extra_values or []:
        penalty += _selector_instability_penalty(str(value or ""))
    return penalty


def locator_has_unstable_identity(locator: Any) -> bool:
    return locator_instability_penalty(locator) >= 10000.0


def _locator_instability_penalty(locator: Dict[str, Any]) -> float:
    method = str(locator.get("method") or "").lower()
    if method == "nth":
        return 10000.0 + _locator_instability_penalty(normalize_locator(locator.get("locator")))
    if method == "nested":
        return (
            _locator_instability_penalty(normalize_locator(locator.get("parent")))
            + _locator_instability_penalty(normalize_locator(locator.get("child")))
        )
    if method == "testid":
        value = str(locator.get("value") or "")
        return 10000.0 if _is_random_like_identity_token(value) else 0.0
    if method == "css":
        return _selector_instability_penalty(str(locator.get("value") or ""))
    return 0.0


def _selector_instability_penalty(selector: str) -> float:
    if not selector:
        return 0.0
    penalty = 0.0
    if re.search(r"\bdata-v-[0-9a-f]{6,}\b", selector, re.IGNORECASE):
        penalty += 10000.0
    for value in _DATA_TEST_ATTR_RE.findall(selector):
        if _is_random_like_identity_token(value):
            penalty += 10000.0
    for value in _CSS_ID_TOKEN_RE.findall(selector):
        if _is_random_like_identity_token(value):
            penalty += 10000.0
    for value in _CSS_CLASS_TOKEN_RE.findall(selector):
        if _is_random_like_identity_token(value):
            penalty += 5000.0
    if selector.count(">") >= 4:
        penalty += 5000.0
    if ">> nth=" in selector or ".nth(" in selector:
        penalty += 5000.0
    if len(selector) >= 160:
        penalty += 1000.0
    return penalty


def _is_random_like_identity_token(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if re.search(r"\bdata-v-[0-9a-f]{6,}\b", lowered):
        return True
    if re.match(r"^[a-z]+-[\w-]+-id-\d{5,}$", text, re.IGNORECASE):
        return True
    if re.search(r"(?:^|[-_])(?:id|uid|uuid)[-_]?\d{5,}$", lowered):
        return True
    suffix_match = re.search(r"[-_]([0-9a-f]{8,})$", lowered)
    if suffix_match and re.search(r"[a-f]", suffix_match.group(1)) and re.search(r"\d", suffix_match.group(1)):
        return True
    return False
