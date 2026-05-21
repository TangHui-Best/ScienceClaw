from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .asset_validation import validate_harness_assets
from .compiler_regression import run_compiler_regression
from .models import HarnessScenarioAsset, HarnessStepCheckpoint
from .snapshot_regression import run_snapshot_regression
from .store import HarnessAssetStore


_URL_RE = re.compile(r"https?://[^\s)>]+")


@dataclass(frozen=True)
class StepReviewEvidence:
    checkpoint: HarnessStepCheckpoint
    trace_events: list[dict[str, Any]]
    expected: dict[str, Any]


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _sanitize_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    def replace_url(match: re.Match[str]) -> str:
        parsed = urlparse(match.group(0))
        if parsed.hostname:
            return f"{parsed.hostname} page"
        return "captured page"

    text = _URL_RE.sub(replace_url, text)
    return re.sub(r"\s+", " ", text).strip()


def _markdown_cell(value: Any) -> str:
    text = _sanitize_text(value)
    if not text:
        return "-"
    return text.replace("|", "\\|")


def _short_json(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(rendered) <= 160:
        return rendered
    return rendered[:157].rstrip() + "..."


def _page_label(url: str, title: str) -> str:
    sanitized_title = _sanitize_text(title)
    if sanitized_title:
        return sanitized_title
    parsed = urlparse(url)
    if parsed.hostname:
        return f"{parsed.hostname} page"
    return _sanitize_text(url) or "captured page"


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    return ""


def _trace_target_evidence(event: dict[str, Any]) -> dict[str, Any]:
    evidence = event.get("target_evidence")
    if isinstance(evidence, dict):
        return evidence
    signals = event.get("signals")
    if isinstance(signals, dict) and isinstance(signals.get("target_evidence"), dict):
        return signals["target_evidence"]
    candidates = event.get("locator_candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            locator = candidate.get("locator")
            if isinstance(locator, dict):
                return {
                    "role": locator.get("role") or locator.get("method") or "",
                    "text": locator.get("name") or locator.get("value") or "",
                }
    return {}


def _target_label(checkpoint: HarnessStepCheckpoint, trace_events: list[dict[str, Any]]) -> str:
    evidence = dict(checkpoint.action.target_evidence or {})
    if not evidence:
        for event in trace_events:
            evidence = _trace_target_evidence(event)
            if evidence:
                break
    role = _sanitize_text(evidence.get("role"))
    text = (
        _first_text(evidence.get("text"))
        or _first_text(evidence.get("label"))
        or _first_text(evidence.get("placeholder"))
        or _first_text(evidence.get("container_text"))
    )
    if role and text:
        return f"{role}: {text}"
    return text or role


def _action_name(checkpoint: HarnessStepCheckpoint, trace_events: list[dict[str, Any]]) -> str:
    if checkpoint.action.expected_action_type:
        return _sanitize_text(checkpoint.action.expected_action_type)
    for event in trace_events:
        action = event.get("action") or event.get("trace_type") or event.get("type")
        if action:
            return _sanitize_text(action)
    return "recorded action"


def _expected_output_keys(expected: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    state_signals = expected.get("state_signals")
    if isinstance(state_signals, dict):
        output_key = _sanitize_text(state_signals.get("output_key"))
        if output_key:
            keys.append(output_key)
    compiler_signals = expected.get("compiler_signals")
    if isinstance(compiler_signals, dict):
        for key in compiler_signals.get("must_preserve_output_keys") or []:
            key_text = _sanitize_text(key)
            if key_text and key_text not in keys:
                keys.append(key_text)
    return keys


def _trace_outputs(trace_events: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    outputs: list[tuple[str, Any]] = []
    for event in trace_events:
        output_key = _sanitize_text(event.get("output_key"))
        if "output" in event and event.get("output") is not None:
            outputs.append((output_key or "observed_output", event.get("output")))
    return outputs


def _observed_output_values(trace_events: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        text = _sanitize_text(value)
        if text and text not in values:
            values.append(text)

    for _key, output in _trace_outputs(trace_events):
        visit(output)
    return values


def _source_hosts(steps: list[StepReviewEvidence]) -> list[str]:
    hosts: list[str] = []
    for step in steps:
        states = [step.checkpoint.before, step.checkpoint.after]
        for state in states:
            if state is None:
                continue
            host = urlparse(state.url).hostname or ""
            if host and host not in hosts:
                hosts.append(host)
    return sorted(hosts)


def _final_output(steps: list[StepReviewEvidence]) -> str:
    for step in reversed(steps):
        outputs = _trace_outputs(step.trace_events)
        if outputs:
            key, value = outputs[-1]
            if isinstance(value, dict) and key in value:
                value = value[key]
            return f"{key} = {_sanitize_text(value)}"
        keys = _expected_output_keys(step.expected)
        if keys:
            return keys[-1]
    return ""


def _confidence(steps: list[StepReviewEvidence]) -> str:
    has_page_transition = any(
        step.checkpoint.after is not None
        and step.checkpoint.before.url != step.checkpoint.after.url
        for step in steps
    )
    has_output = bool(_final_output(steps))
    if len(steps) >= 2 and has_page_transition and has_output:
        return "high"
    if steps and (has_page_transition or has_output):
        return "medium"
    return "low"


def _confidence_label(steps: list[StepReviewEvidence]) -> str:
    return {
        "high": "高",
        "medium": "中",
        "low": "低",
    }[_confidence(steps)]


def _output_summary(evidence: StepReviewEvidence) -> str:
    outputs = _trace_outputs(evidence.trace_events)
    if outputs:
        return "; ".join(f"{key}: {_sanitize_text(_short_json(value))}" for key, value in outputs)
    expected_keys = _expected_output_keys(evidence.expected)
    if expected_keys:
        return ", ".join(expected_keys)
    return ""


def _load_step_evidence(asset_dir: Path, scenario: HarnessScenarioAsset) -> list[StepReviewEvidence]:
    steps: list[StepReviewEvidence] = []
    refs = sorted(scenario.step_checkpoints, key=lambda ref: ref.step_index)
    for ref in refs:
        checkpoint_path = asset_dir / ref.checkpoint_path
        checkpoint = HarnessStepCheckpoint.model_validate(_load_json(checkpoint_path, {}))
        trace_events = _load_json(asset_dir / checkpoint.action.trace_events_path, [])
        if not isinstance(trace_events, list):
            trace_events = []
        trace_events = [event for event in trace_events if isinstance(event, dict)]
        expected = _load_json(asset_dir / checkpoint.expected_path, {}) if checkpoint.expected_path else {}
        if not isinstance(expected, dict):
            expected = {}
        steps.append(StepReviewEvidence(checkpoint=checkpoint, trace_events=trace_events, expected=expected))
    return steps


def _source_dict(scenario: HarnessScenarioAsset) -> dict[str, Any]:
    source = scenario.source
    if isinstance(source, dict):
        return dict(source)
    return source.model_dump(mode="json")


def _infer_identity(scenario: HarnessScenarioAsset, steps: list[StepReviewEvidence]) -> tuple[str, str]:
    sop_intent = _sanitize_text(scenario.sop_intent)
    if sop_intent:
        return sop_intent, "scenario.sop_intent"

    output_step = next((step for step in reversed(steps) if _output_summary(step)), None)
    primary_step = output_step or (steps[-1] if steps else None)
    if primary_step is None:
        return "未命名的 RPA 捕获场景", "兜底推断"

    intent = _sanitize_text(primary_step.checkpoint.step_intent)
    after = primary_step.checkpoint.after
    page = _page_label(
        after.url if after else primary_step.checkpoint.before.url,
        after.title if after else primary_step.checkpoint.before.title,
    )
    target = ""
    for step in steps:
        target = _target_label(step.checkpoint, step.trace_events)
        if target:
            break
    output_keys = [
        key
        for step in steps
        for key in _expected_output_keys(step.expected)
    ]
    observed_values = [
        value
        for step in steps
        for value in _observed_output_values(step.trace_events)
    ]
    pieces = [intent or "捕获的 RPA 场景"]
    if target:
        pieces.append(f"目标 {target}")
    if page:
        pieces.append(f"页面 {page}")
    if output_keys:
        pieces.append(f"({', '.join(dict.fromkeys(output_keys))})")
    if observed_values:
        pieces.append(f"观测值 {_sanitize_text(observed_values[0])}")
    return "，".join(pieces), "来自捕获证据推断"


def _human_sop_lines(steps: list[StepReviewEvidence]) -> list[str]:
    lines: list[str] = []
    for step in steps:
        checkpoint = step.checkpoint
        action = _action_name(checkpoint, step.trace_events)
        target = _target_label(checkpoint, step.trace_events)
        output = _output_summary(step)
        suffixes = []
        if target:
            suffixes.append(f"目标: {target}")
        if output:
            suffixes.append(f"输出: {output}")
        suffix = f" ({'; '.join(suffixes)})" if suffixes else ""
        lines.append(f"{checkpoint.step_index}. {_sanitize_text(checkpoint.step_intent)} - 动作: {action}{suffix}")
    return lines


def _evidence_summary_rows(steps: list[StepReviewEvidence]) -> list[str]:
    rows = ["| 步骤 | 意图 | 前置页面 | 动作 | 后置页面 | 输出 |", "| --- | --- | --- | --- | --- | --- |"]
    for step in steps:
        checkpoint = step.checkpoint
        before = _page_label(checkpoint.before.url, checkpoint.before.title)
        after = _page_label(checkpoint.after.url, checkpoint.after.title) if checkpoint.after else "-"
        action = _action_name(checkpoint, step.trace_events)
        target = _target_label(checkpoint, step.trace_events)
        if target:
            action = f"{action}: {target}"
        rows.append(
            "| "
            + " | ".join(
                [
                    str(checkpoint.step_index),
                    _markdown_cell(checkpoint.step_intent),
                    _markdown_cell(before),
                    _markdown_cell(action),
                    _markdown_cell(after),
                    _markdown_cell(_output_summary(step)),
                ]
            )
            + " |"
        )
    return rows


def _validation_line(validation_report: dict[str, Any]) -> str:
    summary = validation_report.get("summary") or {}
    blocking = int(summary.get("blocking_issue_count") or 0)
    issues = int(summary.get("issue_count") or 0)
    if blocking:
        return f"资产校验: 失败 ({blocking} 个阻塞问题，{issues} 个问题总计)"
    if issues:
        return f"资产校验: 警告 ({issues} 个非阻塞问题)"
    return "资产校验: 通过"


def _runner_line(label: str, report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    total = int(summary.get("total") or 0)
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    status = "通过" if failed == 0 else "警告"
    return f"{label}: {status} ({passed}/{total})"


def _auto_checks(
    *,
    assets_root: Path,
    asset_id: str,
    scenario: HarnessScenarioAsset,
    steps: list[StepReviewEvidence],
) -> list[str]:
    validation = validate_harness_assets(assets_root, asset_ids={asset_id})
    snapshot = run_snapshot_regression(assets_root, asset_ids={asset_id})
    compiler = run_compiler_regression(assets_root, asset_ids={asset_id})
    trace_count = sum(len(step.trace_events) for step in steps)
    accepted_count = sum(
        1
        for step in steps
        for event in step.trace_events
        if event.get("accepted") is True
    )
    runtime_statuses = sorted({step.checkpoint.runtime_result.status for step in steps})
    output_keys = sorted(
        {
            key
            for step in steps
            for key in _expected_output_keys(step.expected)
        }
    )
    governance = scenario.governance
    return [
        _validation_line(validation),
        _runner_line("Snapshot 回归", snapshot),
        _runner_line("Compiler 回归", compiler),
        f"检查点: {len(steps)} 个；运行状态: {', '.join(runtime_statuses) or 'unknown'}",
        f"Trace events: {trace_count} 个；accepted: {accepted_count}",
        f"预期输出字段: {', '.join(output_keys) if output_keys else '无'}",
        (
            "治理状态: "
            f"{governance.promotion_status}；expected reviewed={governance.expected_signals_reviewed}；"
            f"sensitivity reviewed={governance.sensitivity_reviewed}"
        ),
    ]


def _review_questions(scenario: HarnessScenarioAsset, steps: list[StepReviewEvidence]) -> list[str]:
    has_output = any(_output_summary(step) for step in steps)
    questions = [
        "推断出的场景描述是否符合实际录制意图？",
        "SOP 步骤是否准确描述真实用户流程，并且不依赖 live 页面状态？",
        "目标证据和页面标题是否足以识别预期 UI 元素？",
    ]
    if has_output:
        questions.append("观测到的输出值在语义上是否正确，并且适合作为审查证据保留？")
    if scenario.sensitivity == "local-only":
        questions.append("在分享或升级出 local-only 范围前，是否已经确认没有敏感信息？")
    return questions


def _suggested_promotion(scenario: HarnessScenarioAsset) -> str:
    governance = scenario.governance
    if scenario.asset_status == "draft" and governance.promotion_status == "captured":
        return (
            "- candidate-lite: 建议，在人工语义确认后进入非阻塞观察。\n"
            "- blocking candidate: 需要显式确认 expected signals 和 sensitivity。\n"
            "- golden: 不建议，新录制资产不能自动成为 blocking golden。"
        )
    return (
        "- candidate-lite: 保持当前状态，除非审查者要求重新进入观察层。\n"
        "- blocking candidate: 需要显式确认 expected signals 和 sensitivity。\n"
        "- golden: 仅适用于已审查的 blocking 回归资产。"
    )


def build_asset_review_packet(assets_root: str | Path, asset_id: str) -> str:
    root = Path(assets_root)
    asset_dir = root / asset_id
    scenario = HarnessScenarioAsset.model_validate(_load_json(asset_dir / "scenario.json", {}))
    steps = _load_step_evidence(asset_dir, scenario)
    identity, identity_source = _infer_identity(scenario, steps)
    source = _source_dict(scenario)
    hosts = _source_hosts(steps)
    final_output = _final_output(steps)

    lines = [
        "# 资产审查包（Asset Review Packet）",
        "",
        f"资产 ID: `{_sanitize_text(scenario.asset_id)}`",
        f"捕获范围: `{_sanitize_text(scenario.capture_scope)}`",
        f"资产状态: `{_sanitize_text(scenario.asset_status)}`",
        f"敏感级别: `{_sanitize_text(scenario.sensitivity)}`",
        f"捕获时间: `{_sanitize_text(source.get('captured_at')) or 'unknown'}`",
        "",
        "## 场景身份（Scenario Identity）",
        "",
        f"- 推断场景: {_sanitize_text(identity)}",
        f"- 置信度: {_confidence_label(steps)}",
        f"- 来源站点: {', '.join(hosts) if hosts else 'unknown'}",
        f"- 步骤数: {len(steps)}",
        f"- 最终输出: {final_output or '无'}",
        f"- 身份来源: {_sanitize_text(identity_source)}",
        f"- 原始 SOP 意图: {_sanitize_text(scenario.sop_intent) or '(空)'}",
        "",
        "## 人类可读 SOP（Human SOP）",
        "",
        *_human_sop_lines(steps),
        "",
        "## 证据摘要（Evidence Summary）",
        "",
        *_evidence_summary_rows(steps),
        "",
        "## 自动检查（Auto Checks）",
        "",
        *[f"- {line}" for line in _auto_checks(assets_root=root, asset_id=scenario.asset_id, scenario=scenario, steps=steps)],
        "",
        "## 人工确认问题（Review Questions）",
        "",
        *[f"- {question}" for question in _review_questions(scenario, steps)],
        "",
        "## 建议升级（Suggested Promotion）",
        "",
        _suggested_promotion(scenario),
        "",
    ]
    return "\n".join(lines)


def write_asset_review_packet(assets_root: str | Path, asset_id: str) -> Path:
    root = Path(assets_root)
    store = HarnessAssetStore(root)
    review_path = store.capture_dir(asset_id) / "review.md"
    store.write_text(review_path, build_asset_review_packet(root, asset_id))
    return review_path


def write_asset_review_packets(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    selected_dirs = sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []
    reviews: list[dict[str, str]] = []
    for asset_dir in selected_dirs:
        if asset_ids is not None and asset_dir.name not in asset_ids:
            continue
        path = write_asset_review_packet(root, asset_dir.name)
        reviews.append({"asset_id": asset_dir.name, "review_path": path.as_posix()})
    return {
        "summary": {"review_count": len(reviews)},
        "reviews": reviews,
    }
