from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


_TEXT_SUFFIXES = {".json", ".html", ".htm", ".txt", ".md"}
_GENERATED_REPORT_FILENAMES = {
    "sensitivity_scan.json",
    "review_generation_report.json",
}
_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


_PATTERNS: list[tuple[str, str, re.Pattern[str], str]] = [
    (
        "secret/token",
        "critical",
        re.compile(r"\bBearer\s+[A-Za-z0-9._-]{12,}\b", re.IGNORECASE),
        "Bearer-style token literal",
    ),
    (
        "secret/token",
        "critical",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        "GitHub token-like literal",
    ),
    (
        "secret/token",
        "critical",
        re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{12,}\b"),
        "API key-like literal",
    ),
    (
        "secret/token",
        "critical",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "private key block",
    ),
    (
        "credential/password",
        "critical",
        re.compile(r'"password"\s*:\s*"(?!<[A-Z0-9_]+>)[^"]{3,}"', re.IGNORECASE),
        "captured password field value",
    ),
    (
        "credential/password",
        "critical",
        re.compile(r"type=[\"']password[\"'][^>]*value=[\"'](?!<[A-Z0-9_]+>)[^\"']{3,}[\"']", re.IGNORECASE),
        "captured password input value",
    ),
    (
        "financial",
        "high",
        re.compile(r"(?<![A-Za-z0-9])[$¥€£]\s?\d[\d,]*(?:\.\d{2})?(?![A-Za-z0-9])"),
        "currency amount",
    ),
    (
        "financial",
        "high",
        re.compile(r"\b(?:account|card|acct)[_\s-]*(?:number|no|id)?[\"']?\s*[:=]\s*[\"']?\d{12,19}\b", re.IGNORECASE),
        "account or card number-like value",
    ),
    (
        "PII",
        "medium",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "email address",
    ),
    (
        "local-path",
        "medium",
        re.compile(r"\b[A-Za-z]:(?:<span[^>]*>\\\\</span>[^<>\"'\s]+)+"),
        "HTML-rendered local filesystem path",
    ),
    (
        "local-path",
        "medium",
        re.compile(r"\b[A-Za-z]:(?:\\\\)+(?:[^\\/:*?\"<>|\r\n]+(?:\\\\)+)*[^\\/:*?\"<>|\r\n]+"),
        "escaped local filesystem path",
    ),
    (
        "local-path",
        "medium",
        re.compile(r"\b[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*"),
        "local filesystem path",
    ),
    (
        "auth/session",
        "medium",
        re.compile(r"\b(?:sessionid|session_id|set-cookie)\b", re.IGNORECASE),
        "session or cookie marker",
    ),
    (
        "public-web-noise",
        "info",
        re.compile(r"\b(?:authenticity_token|csrf_tokens?|visitor-payload|uploadToken|currentUser|cookie-consent)\b"),
        "common public web page token marker",
    ),
    (
        "sanitized-placeholder",
        "info",
        re.compile(r"<[A-Z][A-Z0-9_]*\d*>"),
        "sanitized placeholder",
    ),
]


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def _selected_asset_dirs(root: Path, asset_ids: set[str] | None) -> list[Path]:
    if not root.exists():
        return []
    dirs = sorted(path for path in root.iterdir() if path.is_dir())
    if asset_ids is None:
        return dirs
    return [path for path in dirs if path.name in asset_ids]


def _iter_text_files(asset_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(asset_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in _GENERATED_REPORT_FILENAMES:
            continue
        if path.suffix.lower() in _TEXT_SUFFIXES:
            files.append(path)
    return files


def _redacted_excerpt(line: str, match: re.Match[str], category: str) -> str:
    replacement = f"<redacted:{category}>"
    start, end = match.span()
    redacted = line[:start] + replacement + line[end:]
    redacted = re.sub(r"\s+", " ", redacted).strip()
    if len(redacted) <= 180:
        return redacted
    return redacted[:177].rstrip() + "..."


def _finding(
    *,
    asset_dir: Path,
    path: Path,
    line_no: int,
    category: str,
    severity: str,
    reason: str,
    line: str,
    match: re.Match[str],
) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "file": path.relative_to(asset_dir).as_posix(),
        "line": line_no,
        "reason": reason,
        "excerpt": _redacted_excerpt(line, match, category),
        "repo_safe_blocker": severity in {"medium", "high", "critical"} and category != "public-web-noise",
    }


def _scan_text_file(asset_dir: Path, path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    findings: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines() or [text], start=1):
        for category, severity, pattern, reason in _PATTERNS:
            for match in pattern.finditer(line):
                findings.append(
                    _finding(
                        asset_dir=asset_dir,
                        path=path,
                        line_no=line_no,
                        category=category,
                        severity=severity,
                        reason=reason,
                        line=line,
                        match=match,
                    )
                )
    return findings


def _visit_contracts(value: Any, contracts: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        contract = value.get("sanitization_contract")
        if isinstance(contract, dict):
            contracts.append(contract)
        for item in value.values():
            _visit_contracts(item, contracts)
    elif isinstance(value, list):
        for item in value:
            _visit_contracts(item, contracts)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _contract_summary(asset_dir: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    contracts: list[dict[str, Any]] = []
    for expected_path in sorted(asset_dir.glob("steps/*/expected.json")):
        _visit_contracts(_load_json(expected_path, {}), contracts)

    placeholders: list[dict[str, Any]] = []
    runtime_secret_refs: list[str] = []
    controlled_fixtures: list[str] = []
    replay_assertions: list[str] = []
    for contract in contracts:
        for placeholder in contract.get("placeholders") or []:
            if isinstance(placeholder, dict):
                token = str(placeholder.get("token") or "").strip()
                if token and all(item.get("token") != token for item in placeholders):
                    placeholders.append(
                        {
                            "token": token,
                            "semantic_type": str(placeholder.get("semantic_type") or "").strip(),
                            "shape": str(placeholder.get("shape") or "").strip(),
                        }
                    )
        runtime_secret_refs.extend(item for item in _string_list(contract.get("runtime_secret_refs")) if item not in runtime_secret_refs)
        controlled_fixtures.extend(item for item in _string_list(contract.get("controlled_fixtures")) if item not in controlled_fixtures)
        replay_assertions.extend(item for item in _string_list(contract.get("replay_assertions")) if item not in replay_assertions)

    has_contract = bool(placeholders or runtime_secret_refs or controlled_fixtures or replay_assertions)
    has_sensitive_findings = any(
        finding["severity"] in {"medium", "high", "critical"}
        and finding["category"] != "public-web-noise"
        for finding in findings
    )
    if has_contract:
        status = "preserved"
    elif has_sensitive_findings:
        status = "needs-contract"
    else:
        status = "not-declared"

    return {
        "status": status,
        "placeholders": placeholders,
        "runtime_secret_refs": runtime_secret_refs,
        "controlled_fixtures": controlled_fixtures,
        "replay_assertions": replay_assertions,
    }


def _risk_level(findings: list[dict[str, Any]]) -> str:
    max_score = 0
    for finding in findings:
        if finding["category"] == "public-web-noise":
            continue
        max_score = max(max_score, _SEVERITY_ORDER.get(finding["severity"], 0))
    if max_score >= _SEVERITY_ORDER["critical"]:
        return "critical"
    if max_score >= _SEVERITY_ORDER["high"]:
        return "high"
    if max_score >= _SEVERITY_ORDER["medium"]:
        return "medium"
    if findings:
        return "low"
    return "none"


def _recommended_sensitivity(risk_level: str, contract: dict[str, Any]) -> str:
    if risk_level == "critical":
        return "sensitive"
    if contract.get("status") == "preserved" and risk_level in {"none", "low"}:
        return "sanitized"
    if risk_level in {"high", "medium"}:
        return "local-only"
    if risk_level == "low":
        return "local-only"
    return "repo-safe"


def scan_harness_asset(assets_root: str | Path, asset_id: str) -> dict[str, Any]:
    root = Path(assets_root)
    asset_dir = root / asset_id
    findings: list[dict[str, Any]] = []
    for path in _iter_text_files(asset_dir):
        findings.extend(_scan_text_file(asset_dir, path))

    contract = _contract_summary(asset_dir, findings)
    risk_level = _risk_level(findings)
    repo_safe_blocked = any(bool(finding.get("repo_safe_blocker")) for finding in findings)
    category_counts = Counter(str(finding["category"]) for finding in findings)
    return {
        "asset_id": asset_id,
        "risk_level": risk_level,
        "recommended_sensitivity": _recommended_sensitivity(risk_level, contract),
        "repo_safe_blocked": repo_safe_blocked,
        "finding_count": len(findings),
        "category_counts": dict(sorted(category_counts.items())),
        "findings": findings,
        "sanitized_replay_contract": contract,
    }


def scan_harness_assets(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    assets = [scan_harness_asset(root, asset_dir.name) for asset_dir in _selected_asset_dirs(root, asset_ids)]
    categories: Counter[str] = Counter()
    recommended: Counter[str] = Counter()
    repo_safe_blocked_asset_ids: list[str] = []
    for asset in assets:
        categories.update(asset["category_counts"])
        recommended.update([asset["recommended_sensitivity"]])
        if asset["repo_safe_blocked"]:
            repo_safe_blocked_asset_ids.append(asset["asset_id"])

    return {
        "schema_version": "rpa-harness-sensitivity-scan-v0",
        "summary": {
            "asset_count": len(assets),
            "finding_count": sum(int(asset["finding_count"]) for asset in assets),
            "repo_safe_blocked_count": len(repo_safe_blocked_asset_ids),
            "repo_safe_blocked_asset_ids": repo_safe_blocked_asset_ids,
            "categories": dict(sorted(categories.items())),
            "recommended_sensitivity": dict(sorted(recommended.items())),
            "sanitized_replay_preserved_count": sum(
                1 for asset in assets if asset["sanitized_replay_contract"]["status"] == "preserved"
            ),
        },
        "assets": assets,
    }


def _single_asset_report(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rpa-harness-sensitivity-scan-v0",
        "summary": {
            "asset_count": 1,
            "finding_count": int(asset.get("finding_count") or 0),
            "repo_safe_blocked_count": 1 if asset.get("repo_safe_blocked") else 0,
            "repo_safe_blocked_asset_ids": [asset["asset_id"]] if asset.get("repo_safe_blocked") else [],
            "categories": dict(asset.get("category_counts") or {}),
            "recommended_sensitivity": {asset["recommended_sensitivity"]: 1},
            "sanitized_replay_preserved_count": (
                1 if asset.get("sanitized_replay_contract", {}).get("status") == "preserved" else 0
            ),
        },
        "assets": [asset],
    }


def write_sensitivity_scan_sidecars(
    assets_root: str | Path,
    report: dict[str, Any],
    *,
    filename: str = "sensitivity_scan.json",
) -> list[dict[str, str]]:
    root = Path(assets_root)
    written: list[dict[str, str]] = []
    for asset in report.get("assets") or []:
        if not isinstance(asset, dict) or not asset.get("asset_id"):
            continue
        path = root / str(asset["asset_id"]) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_single_asset_report(asset), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append({"asset_id": str(asset["asset_id"]), "path": path.as_posix()})
    return written
