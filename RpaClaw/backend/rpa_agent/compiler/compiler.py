"""CoreTrace Timeline 到四文件 SKILL 的确定性 Compiler。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from ..contracts import (
    CoreTraceTimeline,
    SkillDefinition,
    SkillManifest,
    validate_timeline_payload,
)
from .artifacts import (
    CompiledArtifacts,
    publish_artifacts,
    render_artifacts,
    validate_artifacts,
)
from .plan import BrowserCompilePlan, CompileIssue, sort_issues
from .renderers import RENDERER_KINDS


DEFAULT_COMPILER_VERSION = "rpa-agent-compiler/0.1"


@dataclass(frozen=True, slots=True)
class CompileResult:
    status: str
    issues: tuple[CompileIssue, ...]
    artifacts: CompiledArtifacts | None
    output_dir: Path | None


def _error_path(prefix: str, location: tuple[object, ...]) -> str:
    path = prefix
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def _schema_issues(
    exc: Exception,
    *,
    code: str,
    prefix: str,
    payload: object,
) -> list[CompileIssue]:
    details = getattr(exc, "errors", None)
    if not callable(details):
        return [CompileIssue(code, str(exc), None, None, prefix)]
    issues: list[CompileIssue] = []
    for detail in details(include_url=False):
        location = tuple(detail.get("loc", ()))
        message = str(detail.get("msg", exc))
        issue_code = code
        trace_id: str | None = None
        sequence: int | None = None
        if prefix == "timeline" and len(location) >= 2 and location[0] == "traces" and isinstance(location[1], int):
            try:
                raw_trace = payload["traces"][location[1]]
                trace_id = raw_trace.get("trace_id") if isinstance(raw_trace, dict) else None
                raw_sequence = raw_trace.get("sequence") if isinstance(raw_trace, dict) else None
                sequence = raw_sequence if isinstance(raw_sequence, int) else None
            except (KeyError, IndexError, TypeError):
                pass
        path = _error_path(prefix, location)
        if prefix == "timeline":
            issue_code, trace_id, sequence, path = _timeline_issue_location(
                payload=payload,
                message=message,
                error_type=str(detail.get("type", "")),
                default_code=issue_code,
                trace_id=trace_id,
                sequence=sequence,
                path=path,
            )
        issues.append(
            CompileIssue(
                code=issue_code,
                message=message,
                trace_id=trace_id,
                sequence=sequence,
                path=path,
            )
        )
    return issues or [CompileIssue(code, str(exc), None, None, prefix)]


def _timeline_issue_location(
    *,
    payload: object,
    message: str,
    error_type: str,
    default_code: str,
    trace_id: str | None,
    sequence: int | None,
    path: str,
) -> tuple[str, str | None, int | None, str]:
    if error_type == "union_tag_invalid" and ".action" in path:
        return "action.invalid", trace_id, sequence, path
    mappings = (
        ("timeline.page_not_introduced:", "page.not_introduced", "page"),
        ("timeline.page_already_introduced:", "page.already_introduced", "page"),
        ("binding.required:", "binding.required", "trace"),
        ("binding.endpoint_mismatch:", "binding.endpoint_mismatch", "trace"),
        ("effect.navigation_redundant:", "effect.navigation_redundant", "trace"),
        ("effect.combination_not_allowed:", "effect.combination_not_allowed", "trace"),
        ("timeline.variable_not_produced:", "variable.unresolved", "variable"),
        ("timeline.variable_producer_conflict:", "variable.producer_conflict", "variable"),
        ("timeline.data_asset_not_produced:", "asset.unresolved", "asset"),
    )
    marker_data: tuple[str, str] | None = None
    issue_code = default_code
    mode = ""
    for marker, mapped_code, mapped_mode in mappings:
        if marker in message:
            marker_data = (marker, message.split(marker, 1)[1].split(" ", 1)[0])
            issue_code = mapped_code
            mode = mapped_mode
            break
    if marker_data is None or not isinstance(payload, dict):
        return issue_code, trace_id, sequence, path
    marker, raw_value = marker_data
    traces = payload.get("traces", [])
    if not isinstance(traces, list):
        return issue_code, trace_id, sequence, path
    explicit_trace_id = raw_value.split(":", 1)[0] if mode == "trace" else None
    for index, raw_trace in enumerate(traces):
        if not isinstance(raw_trace, dict):
            continue
        matches = False
        local_path = f"timeline.traces[{index}]"
        if explicit_trace_id is not None:
            matches = raw_trace.get("trace_id") == explicit_trace_id
            local_path += ".action" if marker.startswith("binding.required") else ".effects"
        elif mode == "page":
            action = raw_trace.get("action", {})
            effects = raw_trace.get("effects", [])
            matches = (
                raw_trace.get("scope", {}).get("page_ref") == raw_value
                or (isinstance(action, dict) and action.get("page_ref") == raw_value)
                or any(isinstance(effect, dict) and effect.get("page_ref") == raw_value for effect in effects)
            )
            local_path += ".scope.page_ref"
        elif mode in {"variable", "asset"}:
            for binding_index, binding in enumerate(raw_trace.get("data_bindings", [])):
                if isinstance(binding, dict) and binding.get("ref") == raw_value:
                    matches = True
                    local_path += f".data_bindings[{binding_index}].ref"
                    break
        if matches:
            raw_sequence = raw_trace.get("sequence")
            return (
                issue_code,
                raw_trace.get("trace_id") if isinstance(raw_trace.get("trace_id"), str) else None,
                raw_sequence if isinstance(raw_sequence, int) else None,
                local_path,
            )
    return issue_code, trace_id, sequence, path


def _canonical_timeline_hash(timeline: CoreTraceTimeline) -> str:
    payload = timeline.model_dump(mode="json", exclude_unset=True)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _derived_requirements(timeline: CoreTraceTimeline, definition: SkillDefinition) -> list[str]:
    requirements = ["playwright"]
    action_kinds = {trace.action.kind for trace in timeline.traces}
    effect_kinds = {effect.kind for trace in timeline.traces for effect in trace.effects}
    if "agent" in action_kinds or definition.stage_2_rules:
        requirements.append("agent")
    if definition.asset_inputs or definition.asset_outputs:
        requirements.append("data_asset")
    if "download" in effect_kinds:
        if "data_asset" not in requirements:
            requirements.append("data_asset")
        requirements.append("download")
    if "upload" in action_kinds:
        if "data_asset" not in requirements:
            requirements.append("data_asset")
        requirements.append("upload")
    order = ("playwright", "agent", "data_asset", "download", "upload")
    return [item for item in order if item in requirements]


def _declaration_issues(
    timeline: CoreTraceTimeline,
    definition: SkillDefinition,
) -> list[CompileIssue]:
    issues: list[CompileIssue] = []
    input_refs = {item.ref for item in definition.inputs}
    secret_refs = {item.ref for item in definition.secrets}
    asset_input_refs = {item.ref for item in definition.asset_inputs}
    declared_namespaces: list[tuple[str, str]] = []
    declared_namespaces.extend((item.ref, f"inputs[{index}]") for index, item in enumerate(definition.inputs))
    declared_namespaces.extend((item.ref, f"secrets[{index}]") for index, item in enumerate(definition.secrets))
    declared_namespaces.extend((item.ref, f"asset_inputs[{index}]") for index, item in enumerate(definition.asset_inputs))
    declared_namespaces.extend((item.name, f"outputs[{index}]") for index, item in enumerate(definition.outputs))
    declared_namespaces.extend((item.name, f"asset_outputs[{index}]") for index, item in enumerate(definition.asset_outputs))
    seen: dict[str, str] = {}
    for name, path in declared_namespaces:
        if name in seen:
            issues.append(
                CompileIssue(
                    "binding.namespace_ambiguous",
                    f"声明名称 {name!r} 同时出现在 {seen[name]} 与 {path}",
                    None,
                    None,
                    f"skill_definition.{path}",
                )
            )
        else:
            seen[name] = path

    produced_variables: set[str] = set()
    produced_assets: set[str] = set()
    for trace in timeline.traces:
        if trace.action.kind not in RENDERER_KINDS:
            issues.append(
                CompileIssue(
                    "action.unsupported",
                    f"action.kind {trace.action.kind!r} 没有 Renderer",
                    trace.trace_id,
                    trace.sequence,
                    "action.kind",
                )
            )
        for index, binding in enumerate(trace.data_bindings):
            path = f"data_bindings[{index}].ref"
            if binding.kind == "literal" and binding.sensitive:
                issues.append(
                    CompileIssue(
                        "binding.sensitive_literal",
                        "敏感值必须通过 Secret Binding 提供，禁止编译 sensitive literal",
                        trace.trace_id,
                        trace.sequence,
                        f"data_bindings[{index}]",
                    )
                )
            elif binding.kind == "skill_input" and binding.ref not in input_refs:
                issues.append(CompileIssue("binding.input_undeclared", f"Input {binding.ref!r} 未声明", trace.trace_id, trace.sequence, path))
            elif binding.kind == "secret" and binding.ref not in secret_refs:
                issues.append(CompileIssue("binding.secret_undeclared", f"Secret {binding.ref!r} 未声明", trace.trace_id, trace.sequence, path))
            elif binding.kind == "data_asset":
                if binding.direction == "input" and binding.ref not in asset_input_refs and binding.ref not in produced_assets:
                    issues.append(CompileIssue("asset.input_unresolved", f"DataAsset {binding.ref!r} 未声明或未生产", trace.trace_id, trace.sequence, path))
                if binding.direction == "output":
                    produced_assets.add(binding.ref)
            elif binding.kind == "variable" and binding.direction == "output":
                produced_variables.add(binding.ref)

    for index, output in enumerate(definition.outputs):
        if not any(
            output.variable_ref == ref or output.variable_ref.startswith(ref + ".")
            for ref in produced_variables
        ):
            issues.append(
                CompileIssue(
                    "variable.output_unresolved",
                    f"声明输出 {output.variable_ref!r} 在 Timeline 中没有生产者",
                    None,
                    None,
                    f"skill_definition.outputs[{index}].variable_ref",
                )
            )
    for index, output in enumerate(definition.asset_outputs):
        if output.asset_ref not in produced_assets:
            issues.append(
                CompileIssue(
                    "asset.output_unresolved",
                    f"声明资产输出 {output.asset_ref!r} 在 Timeline 中没有生产者",
                    None,
                    None,
                    f"skill_definition.asset_outputs[{index}].asset_ref",
                )
            )
    return issues


def _agent_required_paths(timeline: CoreTraceTimeline) -> dict[str, dict[str, tuple[str, ...]]]:
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    traces = list(timeline.traces)
    for index, trace in enumerate(traces):
        if trace.action.kind != "agent":
            continue
        trace_paths: dict[str, tuple[str, ...]] = {}
        for output in trace.data_bindings:
            if output.direction != "output" or output.kind != "variable":
                continue
            required: set[str] = set()
            prefix = output.ref + "."
            for later in traces[index + 1 :]:
                for binding in later.data_bindings:
                    if binding.direction == "input" and binding.kind == "variable" and binding.ref.startswith(prefix):
                        required.add(binding.ref[len(prefix) :])
            trace_paths[output.name] = tuple(sorted(required))
        result[trace.trace_id] = trace_paths
    return result


class DeterministicCompiler:
    def __init__(self, *, compiler_version: str = DEFAULT_COMPILER_VERSION) -> None:
        if not compiler_version:
            raise ValueError("compiler_version must not be empty")
        self._compiler_version = compiler_version

    def compile(
        self,
        timeline_payload: object,
        definition_payload: object,
        destination: str | Path,
    ) -> CompileResult:
        issues: list[CompileIssue] = []
        definition: SkillDefinition | None = None
        timeline: CoreTraceTimeline | None = None

        try:
            raw_definition = (
                definition_payload.model_dump(mode="json", exclude_unset=True)
                if isinstance(definition_payload, SkillDefinition)
                else definition_payload
            )
            definition = SkillDefinition.model_validate(raw_definition)
        except Exception as exc:
            issues.extend(
                _schema_issues(
                    exc,
                    code="schema.skill_definition",
                    prefix="skill_definition",
                    payload=definition_payload,
                )
            )

        if definition is not None:
            try:
                raw_timeline = (
                    timeline_payload.model_dump(mode="json", exclude_unset=True)
                    if isinstance(timeline_payload, CoreTraceTimeline)
                    else timeline_payload
                )
                timeline = validate_timeline_payload(
                    raw_timeline,
                    external_asset_refs={item.ref for item in definition.asset_inputs},
                )
            except Exception as exc:
                issues.extend(
                    _schema_issues(
                        exc,
                        code="schema.timeline",
                        prefix="timeline",
                        payload=timeline_payload,
                    )
                )
        else:
            issues.append(
                CompileIssue(
                    "schema.timeline",
                    "SkillDefinition 无效，无法建立 Timeline 的外部 DataAsset 边界",
                    None,
                    None,
                    "timeline",
                )
            )

        if definition is None or timeline is None:
            return CompileResult("rejected", sort_issues(issues), None, None)

        issues.extend(_declaration_issues(timeline, definition))
        if issues:
            return CompileResult("rejected", sort_issues(issues), None, None)

        manifest_payload = {
            "schema_version": "skill-manifest/v0.1",
            "skill": definition.skill.model_dump(mode="json"),
            "entrypoint": "skill:execute_skill",
            "runtime": {
                "api_version": "rpa-agent-runtime/0.1",
                "requirements": _derived_requirements(timeline, definition),
            },
            "inputs": [item.model_dump(mode="json", exclude_unset=True) for item in definition.inputs],
            "secrets": [item.model_dump(mode="json") for item in definition.secrets],
            "asset_inputs": [item.model_dump(mode="json") for item in definition.asset_inputs],
            "outputs": [item.model_dump(mode="json") for item in definition.outputs],
            "asset_outputs": [item.model_dump(mode="json") for item in definition.asset_outputs],
            "source": {
                "core_trace_schema_version": timeline.schema_version,
                "trace_count": len(timeline.traces),
                "timeline_hash": _canonical_timeline_hash(timeline),
                "compiler_version": self._compiler_version,
            },
        }
        try:
            manifest = SkillManifest.model_validate(manifest_payload)
        except Exception as exc:
            issue = CompileIssue("artifact.manifest_schema", str(exc), None, None, "skill.manifest.json")
            return CompileResult("rejected", (issue,), None, None)

        plan = BrowserCompilePlan(
            timeline=timeline,
            definition=definition,
            manifest=manifest,
            agent_required_paths=_agent_required_paths(timeline),
        )
        try:
            artifacts = render_artifacts(plan)
        except Exception as exc:
            issue = CompileIssue("artifact.render_failed", str(exc), None, None, "artifacts")
            return CompileResult("rejected", (issue,), None, None)
        sensitive_values = tuple(
            str(binding.value)
            for trace in timeline.traces
            for binding in trace.data_bindings
            if binding.kind == "literal"
            and binding.sensitive
            and binding.value is not None
        )
        issues.extend(validate_artifacts(artifacts, forbidden_values=sensitive_values))
        if issues:
            return CompileResult("rejected", sort_issues(issues), None, None)

        output_dir = Path(destination)
        publish_issue = publish_artifacts(artifacts, output_dir)
        if publish_issue is not None:
            return CompileResult("rejected", (publish_issue,), None, None)
        return CompileResult("published", (), artifacts, output_dir.absolute())
