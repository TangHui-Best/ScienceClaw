from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_REPORT_FILENAMES = {
    "stateful_sop": "stateful_sop_execution_report.json",
    "skill_replay": "skill_replay_execution_report.json",
    "compiler": "compiler_execution_report.json",
    "snapshot": "snapshot_execution_report.json",
}


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


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _truncate(value: Any, limit: int = 220) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _cell(value: Any) -> str:
    text = _truncate(value, 160)
    if not text:
        return "-"
    return text.replace("|", "\\|")


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary")
    return summary if isinstance(summary, dict) else {}


def _status_label(summary: dict[str, Any]) -> str:
    status = str(summary.get("status") or "").strip()
    if status:
        return status
    failed = int(summary.get("failed") or 0)
    return "failed" if failed else "passed"


def _runner_row(name: str, report: dict[str, Any]) -> str:
    summary = _summary(report)
    total = summary.get("total")
    passed = summary.get("passed")
    failed = summary.get("failed")
    model_source = summary.get("runtime_ai_model_config_source") or ""
    categories = summary.get("failure_categories") or {}
    category_text = ", ".join(f"{key}={value}" for key, value in categories.items()) if isinstance(categories, dict) else ""
    return (
        f"| `{name}` | `{_cell(_status_label(summary))}` | {_cell(model_source)} | "
        f"{_cell(total)} | {_cell(passed)} | {_cell(failed)} | {_cell(category_text)} |"
    )


def _first_asset(report: dict[str, Any], asset_id: str) -> dict[str, Any]:
    assets = report.get("assets")
    if not isinstance(assets, list):
        return {}
    for item in assets:
        if isinstance(item, dict) and str(item.get("asset_id") or "") == asset_id:
            return item
    for item in assets:
        if isinstance(item, dict):
            return item
    return {}


def _failed_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    assets = report.get("assets")
    if not isinstance(assets, list):
        return []
    return [item for item in assets if isinstance(item, dict) and item.get("status") == "failed"]


def _issue_label(category: str, error: str = "") -> str:
    haystack = f"{category} {error}".lower()
    if "missing credentials" in haystack or "api_key" in haystack:
        return "模型配置未注入或凭证缺失"
    if category == "compiler-hardcoded-observed-value":
        return "生成 Skill 硬编码录制现场值"
    if category in {"replay-output-shape-mismatch", "controlled-replay-output-shape-mismatch"}:
        return "输出形态与 expected 不一致"
    if category:
        return category
    return "未分类"


def _stateful_verdict(report: dict[str, Any], asset_id: str) -> str:
    summary = _summary(report)
    asset = _first_asset(report, asset_id)
    if int(summary.get("eligible_capture_count") or 0) <= 0:
        return "未触发"
    if int(asset.get("accepted_trace_count") or 0) > 0 or int(asset.get("generated_skill_size") or 0) > 0:
        if asset.get("status") == "passed":
            return "已触发并通过"
        return "已触发但未通过"
    return "已选中但未生成 Skill"


def _service_boundary_lines() -> list[str]:
    return [
        "本报告验证的是 Harness 离线执行入口：已有 asset -> 重建 trace session -> TraceSkillCompiler -> generated Skill -> controlled replay。",
        "它会复用 `RecordingRuntimeAgent` 和 `TraceSkillCompiler` 等核心组件，但不等同于真实 UI/RPA 服务入口。",
        "真实 UI/RPA 服务入口通常会先解析用户选择的模型配置或数据库中的默认模型配置，再把 `model_config` 透传给 runtime AI。",
        "当前 generated Skill 的 runtime AI 只读取 `_runtime_context.runtime_ai.model_config` 或 `_model_config`；如果 runner 没注入这些配置，即使项目 `.env` 里有其它命名的凭证，也会在 replay 时表现为模型凭证缺失。",
    ]


def _render_failure_rows(reports: dict[str, dict[str, Any]]) -> list[str]:
    rows = [
        "| Runner | Step | 问题 | 证据 |",
        "| --- | --- | --- | --- |",
    ]
    found = False
    for runner in ["stateful_sop", "skill_replay", "compiler"]:
        report = reports.get(runner, {})
        if runner == "stateful_sop":
            for item in _failed_items(report):
                replay = item.get("replay") if isinstance(item.get("replay"), dict) else {}
                category = str(item.get("failure_category") or replay.get("failure_category") or "")
                error = str(item.get("error") or replay.get("error") or "")
                rows.append(f"| `{runner}` | SOP | {_cell(_issue_label(category, error))} | {_cell(error or category)} |")
                found = True
            continue
        for item in _failed_items(report):
            category = str(item.get("failure_category") or "")
            error = str(item.get("error") or "")
            evidence = error or ", ".join(str(value) for value in item.get("hardcoded_values") or []) or category
            rows.append(
                f"| `{runner}` | {_cell(item.get('step_index'))} | "
                f"{_cell(_issue_label(category, error))} | {_cell(evidence)} |"
            )
            found = True
    if not found:
        rows.append("| - | - | 未发现失败项 | - |")
    return rows


def _has_missing_credentials_failure(reports: dict[str, dict[str, Any]]) -> bool:
    for report in reports.values():
        for item in _failed_items(report):
            replay = item.get("replay") if isinstance(item.get("replay"), dict) else {}
            text = " ".join(
                [
                    str(item.get("failure_category") or ""),
                    str(item.get("error") or ""),
                    str(replay.get("failure_category") or ""),
                    str(replay.get("error") or ""),
                ]
            ).lower()
            if "missing credentials" in text or "api_key" in text:
                return True
    return False


def _suggested_next_actions(reports: dict[str, dict[str, Any]]) -> list[str]:
    if _has_missing_credentials_failure(reports):
        first = "- 若目标是模拟真实 UI/RPA 服务入口，应让 runner 注入真实服务解析出的 `model_config`，或显式支持 `--model-config-file`。"
    else:
        first = "- 当前执行报告未再出现模型凭证缺失；后续应继续处理 replay 输出形态和 compiler 泛化问题。"
    return [
        first,
        "- 若目标是让该资产进入 blocking baseline，应先人工确认 expected signals 和 sensitivity。",
        "- 若 compiler 报 `compiler-hardcoded-observed-value`，应修 TraceSkillCompiler 泛化逻辑，而不是修改录制事实。",
        "- 若 replay 报输出形态不匹配，应对齐 generated Skill 输出结构和 `expected.json` 的 `observed_output_shape`。",
    ]


def _render_markdown(asset_dir: Path, scenario: dict[str, Any], reports: dict[str, dict[str, Any]]) -> str:
    asset_id = str(scenario.get("asset_id") or asset_dir.name)
    governance = scenario.get("governance") if isinstance(scenario.get("governance"), dict) else {}
    stateful = reports.get("stateful_sop", {})
    stateful_asset = _first_asset(stateful, asset_id)
    stateful_verdict = _stateful_verdict(stateful, asset_id)
    runtime_keys = stateful_asset.get("runtime_result_keys") or []

    lines = [
        "# 执行审查报告（Execution Review）",
        "",
        f"资产 ID: `{asset_id}`",
        f"资产状态: `{scenario.get('asset_status') or ''}`",
        f"Promotion: `{governance.get('promotion_status') or ''}`",
        f"Sensitivity: `{scenario.get('sensitivity') or ''}`",
        f"Expected reviewed: `{governance.get('expected_signals_reviewed')}`",
        f"Sensitivity reviewed: `{governance.get('sensitivity_reviewed')}`",
        "",
        "## 结论摘要",
        "",
        f"- SOP→Skill 链路: {stateful_verdict}",
        f"- 重建 trace 数: `{stateful_asset.get('accepted_trace_count') or 0}`",
        f"- generated Skill size: `{stateful_asset.get('generated_skill_size') or 0}`",
        f"- Runtime result keys: `{', '.join(str(item) for item in runtime_keys) or 'none'}`",
        "",
        "## 执行入口边界",
        "",
        *_service_boundary_lines(),
        "",
        "## Runner Summary",
        "",
        "| Runner | Status | Runtime AI Config | Total | Passed | Failed | Failure Categories |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *[_runner_row(name, reports.get(name, {})) for name in ["snapshot", "compiler", "skill_replay", "stateful_sop"]],
        "",
        "## Failure Analysis",
        "",
        *_render_failure_rows(reports),
        "",
        "## Report Files",
        "",
        *[
            f"- `{filename}`: {'present' if (asset_dir / filename).exists() else 'missing'}"
            for filename in _REPORT_FILENAMES.values()
        ],
        "",
        "## Suggested Next Actions",
        "",
        *_suggested_next_actions(reports),
        "",
    ]
    return "\n".join(lines)


def write_asset_execution_review_packet(asset_dir: str | Path) -> dict[str, Any]:
    asset_path = Path(asset_dir)
    scenario = _load_json(asset_path / "scenario.json", {})
    if not isinstance(scenario, dict):
        scenario = {}
    reports = {
        key: _load_json(asset_path / filename, {})
        for key, filename in _REPORT_FILENAMES.items()
    }
    reports = {key: value if isinstance(value, dict) else {} for key, value in reports.items()}
    output_path = asset_path / "execution_review.md"
    output_path.write_text(_render_markdown(asset_path, scenario, reports), encoding="utf-8")
    return {
        "asset_id": str(scenario.get("asset_id") or asset_path.name),
        "status": "generated",
        "path": output_path.as_posix(),
        "missing_reports": [
            filename for filename in _REPORT_FILENAMES.values() if not (asset_path / filename).exists()
        ],
    }


def write_asset_execution_review_packets(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    assets = [write_asset_execution_review_packet(asset_dir) for asset_dir in _selected_asset_dirs(root, asset_ids)]
    return {
        "schema_version": "rpa-harness-asset-execution-review-generation-v0",
        "summary": {
            "asset_count": len(assets),
            "generated_count": len([item for item in assets if item.get("status") == "generated"]),
        },
        "assets": assets,
    }
