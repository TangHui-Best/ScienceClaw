from __future__ import annotations

import re
from typing import Any


_COMMON_LABEL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("用户名", " username "),
    ("用户名称", " username "),
    ("账号", " account "),
    ("帐号", " account "),
    ("账户", " account "),
    ("密码", " password "),
    ("口令", " password "),
    ("查询条件", " query "),
    ("查询", " query "),
    ("搜索", " search "),
    ("关键字", " keyword "),
    ("关键词", " keyword "),
    ("文件名", " filename "),
    ("名称", " name "),
)

_PROMPT_WORD_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("请输入", " "),
    ("请填写", " "),
    ("输入", " "),
    ("填写", " "),
    ("请选择", " "),
    ("选择", " "),
)


def slug_input_key(value: str) -> str:
    text = str(value or "").strip().lower()
    for source, target in _PROMPT_WORD_REPLACEMENTS:
        text = text.replace(source, target)
    for source, target in _COMMON_LABEL_REPLACEMENTS:
        text = text.replace(source, target)
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text:
        return "input"
    if text[0].isdigit():
        text = f"input_{text}"
    return text[:48] or "input"


def derive_fill_input_key(trace_event: dict[str, Any]) -> str:
    signals = trace_event.get("signals") if isinstance(trace_event.get("signals"), dict) else {}
    contract = signals.get("input_contract") if isinstance(signals.get("input_contract"), dict) else {}
    if contract.get("input_key"):
        return slug_input_key(str(contract.get("input_key") or ""))

    for key in _trace_evidence_keys(trace_event):
        slug = slug_input_key(key)
        if slug != "input":
            return slug

    candidates = [item for item in trace_event.get("locator_candidates") or [] if isinstance(item, dict)]
    candidates.sort(key=lambda item: 0 if item.get("selected") else 1)
    for candidate in candidates:
        locator = candidate.get("locator") if isinstance(candidate.get("locator"), dict) else candidate
        key = _locator_input_key(locator)
        if key:
            return key

    return "input"


def _trace_evidence_keys(trace_event: dict[str, Any]) -> list[str]:
    evidence = trace_event.get("target_evidence")
    if not isinstance(evidence, dict):
        return []
    keys: list[str] = []
    for field in ("testid", "label", "placeholder", "name", "title", "alt", "text", "role"):
        value = str(evidence.get(field) or "").strip()
        if value:
            keys.append(value)
    return keys


def _locator_input_key(locator: Any) -> str:
    if not isinstance(locator, dict):
        return ""
    method = str(locator.get("method") or "").strip().lower()

    if method == "nested":
        child_key = _locator_input_key(locator.get("child"))
        if child_key:
            return child_key
        return _locator_input_key(locator.get("parent"))

    if method == "nth":
        index = _safe_one_based_index(locator.get("index"))
        base = locator.get("locator", locator.get("base"))
        base_key = _locator_input_key(base)
        if base_key:
            return f"{base_key}_{index}"
        return f"input_{index}"

    if method in {"label", "placeholder", "testid", "title", "alt", "text", "name", "id"}:
        key = _first_non_empty(locator.get("value"), locator.get("name"))
        if key:
            return slug_input_key(key)

    if method == "role":
        name = _first_non_empty(locator.get("name"), locator.get("value"))
        if name:
            return slug_input_key(name)
        role = str(locator.get("role") or "").strip()
        if role:
            return slug_input_key(role)

    key = _first_non_empty(locator.get("name"), locator.get("value"), locator.get("role"))
    if key:
        return slug_input_key(key)
    return ""


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_one_based_index(value: object) -> int:
    try:
        index = int(value)
    except (TypeError, ValueError):
        index = 0
    return max(0, index) + 1
