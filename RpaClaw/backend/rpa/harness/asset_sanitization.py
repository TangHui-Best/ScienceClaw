from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from .sensitivity_scan import _GENERATED_REPORT_FILENAMES


_TEXT_SUFFIXES = {".json", ".html", ".htm", ".txt", ".md"}
_COPIED_GENERATED_FILENAMES = {
    "review.md",
    "review_generation_report.json",
    "sensitivity_scan.json",
    "sanitization_report.json",
    "sanitization_report_cli.json",
}

_SANITIZE_PATTERNS: list[tuple[str, str, str, str, re.Pattern[str]]] = [
    (
        "credential/password",
        "PASSWORD",
        "password",
        "credential",
        re.compile(r'(?P<prefix>"password"\s*:\s*")(?!<[A-Z0-9_]+>)(?P<value>[^"]{3,})(?P<suffix>")', re.IGNORECASE),
    ),
    (
        "credential/password",
        "PASSWORD",
        "password",
        "credential",
        re.compile(
            r'(?P<prefix>type=["\']password["\'][^>]*value=["\'])(?!<[A-Z0-9_]+>)(?P<value>[^"\']{3,})(?P<suffix>["\'])',
            re.IGNORECASE,
        ),
    ),
    (
        "secret/token",
        "TOKEN",
        "secret_token",
        "secret",
        re.compile(r"(?P<value>\bBearer\s+[A-Za-z0-9._-]{12,}\b)", re.IGNORECASE),
    ),
    (
        "secret/token",
        "TOKEN",
        "secret_token",
        "secret",
        re.compile(r"(?P<value>\bgh[pousr]_[A-Za-z0-9_]{20,}\b)"),
    ),
    (
        "secret/token",
        "TOKEN",
        "secret_token",
        "secret",
        re.compile(r"(?P<value>\bsk-[A-Za-z0-9][A-Za-z0-9_-]{12,}\b)"),
    ),
    (
        "financial",
        "AMOUNT",
        "currency_amount",
        "money",
        re.compile(r"(?P<value>(?<![A-Za-z0-9])[$¥€£]\s?\d[\d,]*(?:\.\d{2})?(?![A-Za-z0-9]))"),
    ),
    (
        "financial",
        "ACCOUNT",
        "account_identifier",
        "numeric_identifier",
        re.compile(r"(?P<value>\b(?:account|card|acct)[_\s-]*(?:number|no|id)?[\"']?\s*[:=]\s*[\"']?\d{12,19}\b)", re.IGNORECASE),
    ),
    (
        "PII",
        "EMAIL",
        "email",
        "email",
        re.compile(r"(?P<value>\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)"),
    ),
    (
        "local-path",
        "LOCAL_PATH",
        "local_path",
        "path",
        re.compile(r"(?P<value>\b[A-Za-z]:(?:<span[^>]*>\\\\</span>[^<>\"'\s]+)+)"),
    ),
    (
        "local-path",
        "LOCAL_PATH",
        "local_path",
        "path",
        re.compile(r"(?P<value>\b[A-Za-z]:(?:\\\\)+(?:[^\\/:*?\"<>|\r\n]+(?:\\\\)+)*[^\\/:*?\"<>|\r\n]+)"),
    ),
    (
        "local-path",
        "LOCAL_PATH",
        "local_path",
        "path",
        re.compile(r"(?P<value>\b[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*)"),
    ),
    (
        "auth/session",
        "SESSION_ID",
        "session_identifier",
        "identifier",
        re.compile(
            r'(?P<prefix>"(?:sessionid|session_id|set-cookie)"\s*:\s*")(?!<[A-Z0-9_]+>)(?P<value>[^"]+)(?P<suffix>")',
            re.IGNORECASE,
        ),
    ),
    (
        "auth/session",
        "SESSION_ID",
        "session_identifier",
        "identifier",
        re.compile(r"(?P<value>\b(?:sessionid|session_id|set-cookie)\b)", re.IGNORECASE),
    ),
]


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class _SanitizationState:
    def __init__(self) -> None:
        self._by_value: dict[tuple[str, str], str] = {}
        self._counters: defaultdict[str, int] = defaultdict(int)
        self.placeholders: list[dict[str, str]] = []
        self.replacements: list[dict[str, str]] = []

    def token_for(
        self,
        *,
        category: str,
        family: str,
        semantic_type: str,
        shape: str,
        value: str,
    ) -> str:
        key = (family, value)
        if key in self._by_value:
            return self._by_value[key]
        self._counters[family] += 1
        token = f"<{family}_{self._counters[family]}>"
        self._by_value[key] = token
        self.placeholders.append(
            {
                "token": token,
                "category": category,
                "semantic_type": semantic_type,
                "shape": shape,
            }
        )
        self.replacements.append(
            {
                "category": category,
                "token": token,
                "semantic_type": semantic_type,
                "shape": shape,
            }
        )
        return token


def _replace_match(match: re.Match[str], state: _SanitizationState, category: str, family: str, semantic_type: str, shape: str) -> str:
    value = match.groupdict().get("value") or match.group(0)
    token = state.token_for(
        category=category,
        family=family,
        semantic_type=semantic_type,
        shape=shape,
        value=value,
    )
    prefix = match.groupdict().get("prefix") or ""
    suffix = match.groupdict().get("suffix") or ""
    return f"{prefix}{token}{suffix}"


def _sanitize_text(text: str, state: _SanitizationState) -> str:
    sanitized = text
    for category, family, semantic_type, shape, pattern in _SANITIZE_PATTERNS:
        sanitized = pattern.sub(
            lambda match, category=category, family=family, semantic_type=semantic_type, shape=shape: _replace_match(
                match,
                state,
                category,
                family,
                semantic_type,
                shape,
            ),
            sanitized,
        )
    return sanitized


def _iter_text_files(asset_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(asset_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in _GENERATED_REPORT_FILENAMES or path.name == "sanitization_report.json":
            continue
        if path.suffix.lower() in _TEXT_SUFFIXES:
            files.append(path)
    return files


def _copy_asset(source_dir: Path, target_dir: Path, *, overwrite: bool) -> None:
    if target_dir.exists():
        if not overwrite:
            raise FileExistsError(f"sanitized asset already exists: {target_dir}")
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)


def _remove_copied_generated_files(target_dir: Path) -> None:
    for path in sorted(target_dir.rglob("*")):
        if path.is_file() and path.name in _COPIED_GENERATED_FILENAMES:
            path.unlink()


def _update_scenario(target_dir: Path, source_asset_id: str, target_asset_id: str) -> None:
    path = target_dir / "scenario.json"
    scenario = _load_json(path, {})
    scenario["asset_id"] = target_asset_id
    scenario["sensitivity"] = "sanitized"
    environment = scenario.get("environment")
    if not isinstance(environment, dict):
        environment = {}
    environment["sanitized_from_asset_id"] = source_asset_id
    environment["sanitization_report_path"] = "sanitization_report.json"
    scenario["environment"] = environment
    governance = scenario.get("governance")
    if isinstance(governance, dict):
        governance["sensitivity_reviewed"] = False
        governance["expected_signals_reviewed"] = False
        governance["promotion_status"] = governance.get("promotion_status") or "captured"
        notes = str(governance.get("review_notes") or "").strip()
        suffix = f"Sanitized copy derived from {source_asset_id}; human review required before candidate/golden promotion."
        governance["review_notes"] = f"{notes} {suffix}".strip()
    _write_json(path, scenario)


def _update_expected_contracts(target_dir: Path, state: _SanitizationState) -> None:
    contract = {
        "placeholders": state.placeholders,
        "runtime_secret_refs": [],
        "controlled_fixtures": [],
        "replay_assertions": [
            "sanitized asset preserves output shape and SOP replay evidence",
            "raw sensitive values are replaced by semantic placeholders",
        ],
    }
    for expected_path in sorted(target_dir.glob("steps/*/expected.json")):
        expected = _load_json(expected_path, {})
        if not isinstance(expected, dict):
            expected = {}
        state_signals = expected.get("state_signals")
        if not isinstance(state_signals, dict):
            state_signals = {}
        state_signals["sanitization_contract"] = contract
        expected["state_signals"] = state_signals
        _write_json(expected_path, expected)


def sanitize_harness_asset(
    assets_root: str | Path,
    asset_id: str,
    *,
    target_asset_id: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    root = Path(assets_root)
    source_dir = root / asset_id
    if not source_dir.exists():
        raise FileNotFoundError(f"source asset not found: {source_dir}")
    target_id = target_asset_id or f"{asset_id}-sanitized"
    target_dir = root / target_id
    _copy_asset(source_dir, target_dir, overwrite=overwrite)
    _remove_copied_generated_files(target_dir)

    state = _SanitizationState()
    for path in _iter_text_files(target_dir):
        text = path.read_text(encoding="utf-8", errors="ignore")
        sanitized = _sanitize_text(text, state)
        if sanitized != text:
            path.write_text(sanitized, encoding="utf-8")

    _update_scenario(target_dir, asset_id, target_id)
    _update_expected_contracts(target_dir, state)

    report = {
        "schema_version": "rpa-harness-sanitization-report-v0",
        "source_asset_id": asset_id,
        "target_asset_id": target_id,
        "target_path": target_dir.as_posix(),
        "placeholder_count": len(state.placeholders),
        "placeholders": state.placeholders,
        "replacement_count": len(state.replacements),
        "raw_asset_preserved": True,
    }
    _write_json(target_dir / "sanitization_report.json", report)
    return report
