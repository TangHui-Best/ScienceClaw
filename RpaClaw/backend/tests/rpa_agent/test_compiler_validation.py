from __future__ import annotations

import ast
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rpa_agent.configuration import SkillConfigurationDraft, transform_configuration
from rpa_agent.compiler import DeterministicCompiler, RENDERER_KINDS
from rpa_agent.compiler.artifacts import CompiledArtifacts, validate_artifacts
from rpa_agent.contracts import TraceCandidate
from rpa_agent.contracts.models import PageActivatedFact


EXAMPLE = Path(__file__).parents[1] / "contracts" / "golden" / "first_e2e"


def _payloads() -> tuple[dict, dict]:
    timeline = json.loads((EXAMPLE / "coretrace.timeline.json").read_text(encoding="utf-8"))
    definition = json.loads((EXAMPLE / "skill.definition.json").read_text(encoding="utf-8"))
    return timeline, definition


def test_compiler_rejects_wrong_input_domain_without_artifacts(tmp_path: Path) -> None:
    destination = tmp_path / "skill"
    result = DeterministicCompiler().compile(
        {"candidate_id": "candidate_001"},
        {"draft_id": "draft_001"},
        destination,
    )

    assert result.status == "rejected"
    assert result.artifacts is None
    assert sorted({issue.code for issue in result.issues}) == [
        "schema.skill_definition",
        "schema.timeline",
    ]
    assert not destination.exists()


def test_compiler_collects_stably_sorted_schema_issues(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    timeline["traces"][0]["sequence"] = "ten"
    timeline["traces"][1]["action"] = {"kind": "unsupported"}
    definition["skill"]["version"] = "not-semver"

    result = DeterministicCompiler().compile(timeline, definition, tmp_path / "skill")

    assert result.status == "rejected"
    assert result.artifacts is None
    assert list(result.issues) == sorted(
        result.issues,
        key=lambda item: (
            item.sequence is None,
            item.sequence if item.sequence is not None else 0,
            item.path,
            item.code,
        ),
    )
    assert all(issue.code and issue.message and issue.path for issue in result.issues)


def test_invalid_compile_never_overwrites_existing_published_skill(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    destination = tmp_path / "skill"
    destination.mkdir()
    sentinel = destination / "skill.py"
    sentinel.write_text("# existing publication\n", encoding="utf-8")
    timeline["traces"][0]["scope"]["page_ref"] = "missing_page"

    result = DeterministicCompiler().compile(timeline, definition, destination)

    assert result.status == "rejected"
    assert result.artifacts is None
    assert sentinel.read_text(encoding="utf-8") == "# existing publication\n"
    assert sorted(path.name for path in destination.iterdir()) == ["skill.py"]


def test_skill_definition_outputs_must_have_timeline_producers(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    definition["outputs"][0]["variable_ref"] = "从未产生的结果"

    result = DeterministicCompiler().compile(timeline, definition, tmp_path / "skill")

    assert result.status == "rejected"
    assert result.artifacts is None
    issue = next(issue for issue in result.issues if issue.code == "variable.output_unresolved")
    assert issue.trace_id is None
    assert issue.sequence is None
    assert issue.path == "skill_definition.outputs[0].variable_ref"


def test_compiler_has_one_explicit_renderer_for_every_v01_action_kind() -> None:
    assert RENDERER_KINDS == frozenset(
        {
            "navigate",
            "click",
            "fill",
            "press",
            "select",
            "set_checked",
            "hover",
            "upload",
            "scroll",
            "extract",
            "switch_page",
            "close_page",
            "agent",
        }
    )


def test_existing_symlink_destination_is_rejected_without_escape(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "skill"
    try:
        destination.symlink_to(outside, target_is_directory=True)
    except OSError:
        return

    result = DeterministicCompiler().compile(timeline, definition, destination)

    assert result.status == "rejected"
    assert result.artifacts is None
    assert any(issue.code == "artifact.path_unsafe" for issue in result.issues)
    assert not list(outside.iterdir())


def test_all_v01_action_renderers_produce_explicit_step_code(tmp_path: Path) -> None:
    target = {
        "name": "目标控件",
        "locators": [{"strategy": "test_id", "value": "stable-target", "exact": True}],
    }
    scalar = lambda name, value: {
        "name": name,
        "direction": "input",
        "kind": "literal",
        "value": value,
        "sensitive": False,
    }
    traces = [
        {"trace_id": "t_navigate", "sequence": 10, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "navigate", "mode": "url"}, "data_bindings": [scalar("url", "https://example.invalid/stable")], "effects": []},
        {"trace_id": "t_click", "sequence": 20, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "click", "target": target}, "data_bindings": [], "effects": [{"kind": "new_page", "page_ref": "popup"}]},
        {"trace_id": "t_fill", "sequence": 30, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "fill", "target": target}, "data_bindings": [scalar("value", "业务常量")], "effects": []},
        {"trace_id": "t_press", "sequence": 40, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "press", "target": target}, "data_bindings": [scalar("keys", "Enter")], "effects": []},
        {"trace_id": "t_select", "sequence": 50, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "select", "target": target}, "data_bindings": [scalar("option", "stable-option")], "effects": []},
        {"trace_id": "t_checked", "sequence": 60, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "set_checked", "target": target, "checked": True}, "data_bindings": [], "effects": []},
        {"trace_id": "t_hover", "sequence": 70, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "hover", "target": target}, "data_bindings": [], "effects": []},
        {"trace_id": "t_upload", "sequence": 80, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "upload", "target": target}, "data_bindings": [{"name": "file", "direction": "input", "kind": "data_asset", "ref": "upload_file", "sensitive": False}], "effects": []},
        {"trace_id": "t_scroll", "sequence": 90, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "scroll", "direction": "down", "amount": 1, "unit": "viewport"}, "data_bindings": [], "effects": []},
        {"trace_id": "t_extract", "sequence": 100, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "extract", "target": target, "mode": "text"}, "data_bindings": [{"name": "result", "direction": "output", "kind": "variable", "ref": "中间结果", "sensitive": False}], "effects": []},
        {"trace_id": "t_agent", "sequence": 110, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "agent", "instruction": "将输入转换为最终结果"}, "data_bindings": [{"name": "source", "direction": "input", "kind": "variable", "ref": "中间结果", "sensitive": False}, {"name": "result", "direction": "output", "kind": "variable", "ref": "最终结果", "sensitive": False}], "effects": []},
        {"trace_id": "t_switch", "sequence": 120, "scope": {"page_ref": "main", "frame_path": []}, "action": {"kind": "switch_page", "page_ref": "popup"}, "data_bindings": [], "effects": []},
        {"trace_id": "t_close", "sequence": 130, "scope": {"page_ref": "popup", "frame_path": []}, "action": {"kind": "close_page"}, "data_bindings": [], "effects": []},
    ]
    definition = {
        "schema_version": "skill-definition/v0.1",
        "skill": {"id": "all-actions", "name": "全部动作", "version": "0.1.0", "description": "验证十三种动作均有显式 Renderer"},
        "inputs": [],
        "secrets": [],
        "asset_inputs": [{"ref": "upload_file", "title": "上传文件", "required": True}],
        "outputs": [{"name": "result", "title": "最终结果", "variable_ref": "最终结果", "value_type": "string"}],
        "asset_outputs": [],
        "stage_2_rules": None,
    }

    result = DeterministicCompiler().compile(
        {"schema_version": "core-trace/v0.1", "traces": traces},
        definition,
        tmp_path / "skill",
    )

    assert result.status == "published", result.issues
    source = result.artifacts.files["browser_segment.py"]  # type: ignore[union-attr]
    for trace in traces:
        assert f"step_{trace['sequence']:03d}_{trace['action']['kind']}" in source
    for call in ("page.goto", "target.click", "target.fill", "target.press", "ctx.steps.select_option", "target.check", "target.hover", "target.set_input_files", "page.evaluate", "target.inner_text", "ctx.agent.execute", "ctx.pages.activate", "ctx.pages.close"):
        assert call in source


def test_generated_select_delegates_once_and_does_not_reinterpret_page_failure(tmp_path: Path) -> None:
    timeline = {
        "schema_version": "core-trace/v0.1",
        "traces": [
            {
                "trace_id": "trace_select",
                "sequence": 10,
                "scope": {"page_ref": "main", "frame_path": []},
                "action": {
                    "kind": "select",
                    "target": {
                        "name": "状态",
                        "locators": [{"strategy": "label", "value": "状态", "exact": True}],
                    },
                },
                "data_bindings": [
                    {
                        "name": "option",
                        "direction": "input",
                        "kind": "literal",
                        "value": "待验收",
                        "sensitive": False,
                    }
                ],
                "effects": [],
            }
        ],
    }
    definition = {
        "schema_version": "skill-definition/v0.1",
        "skill": {"id": "select-step", "name": "选择状态", "version": "0.1.0", "description": "验证 select 失败边界"},
        "inputs": [], "secrets": [], "asset_inputs": [], "outputs": [], "asset_outputs": [], "stage_2_rules": None,
    }
    result = DeterministicCompiler().compile(timeline, definition, tmp_path / "skill")
    source = result.artifacts.files["browser_segment.py"]  # type: ignore[union-attr]
    tree = ast.parse(source)
    step_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "step_010_select"
    )
    step_source = ast.get_source_segment(source, step_node) or ""
    assert "except Exception" not in step_source
    assert "target.select_option" not in step_source
    assert "await ctx.steps.select_option(target=target, option=option)" in step_source

    class PageCrashed(RuntimeError):
        pass

    class CrashingTarget:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def select_option(self, **kwargs: object) -> list[str]:
            self.calls.append(dict(kwargs))
            if "value" in kwargs:
                raise PageCrashed("PAGE_CRASHED")
            return ["label-fallback-would-hide-crash"]

    class CrashingSteps:
        def __init__(self) -> None:
            self.calls = 0

        async def select_option(self, *, target: object, option: str) -> None:
            self.calls += 1
            raise PageCrashed("PAGE_CRASHED")

    target = CrashingTarget()
    steps = CrashingSteps()

    async def async_value(value: object) -> object:
        return value

    namespace: dict[str, object] = {"RunContext": object}
    exec(compile(ast.Module(body=[step_node], type_ignores=[]), "generated-select", "exec"), namespace)
    ctx = SimpleNamespace(
        pages=SimpleNamespace(require=lambda _ref: object()),
        frames=SimpleNamespace(resolve=lambda page, frame_path: async_value(page)),
        locators=SimpleNamespace(resolve=lambda **_kwargs: async_value(target)),
        steps=steps,
    )

    with pytest.raises(PageCrashed, match="PAGE_CRASHED"):
        asyncio.run(namespace["step_010_select"](ctx))
    assert steps.calls == 1
    assert target.calls == []


def test_sensitive_literal_is_rejected_before_render_and_never_reaches_artifacts(tmp_path: Path) -> None:
    secret = "UNIQUE_SECRET_7f9e2c"
    destination = tmp_path / "skill"
    destination.mkdir()
    sentinel = destination / "skill.py"
    sentinel.write_text("# existing publication\n", encoding="utf-8")
    timeline = {
        "schema_version": "core-trace/v0.1",
        "traces": [
            {
                "trace_id": "trace_secret",
                "sequence": 10,
                "scope": {"page_ref": "main", "frame_path": []},
                "action": {
                    "kind": "fill",
                    "target": {
                        "name": "密码",
                        "locators": [{"strategy": "label", "value": "密码", "exact": True}],
                    },
                },
                "data_bindings": [
                    {
                        "name": "value",
                        "direction": "input",
                        "kind": "literal",
                        "value": secret,
                        "sensitive": True,
                    }
                ],
                "effects": [],
            }
        ],
    }
    definition = {
        "schema_version": "skill-definition/v0.1",
        "skill": {"id": "secret-leak", "name": "秘密输入", "version": "0.1.0", "description": "敏感 literal 必须失败"},
        "inputs": [], "secrets": [], "asset_inputs": [], "outputs": [], "asset_outputs": [], "stage_2_rules": None,
    }

    result = DeterministicCompiler().compile(timeline, definition, destination)

    assert result.status == "rejected"
    assert result.artifacts is None
    issue = next(issue for issue in result.issues if issue.code == "binding.sensitive_literal")
    assert (issue.trace_id, issue.sequence, issue.path) == (
        "trace_secret",
        10,
        "data_bindings[0]",
    )
    assert sentinel.read_text(encoding="utf-8") == "# existing publication\n"
    assert secret not in "\n".join(path.read_text(encoding="utf-8") for path in destination.iterdir())


def test_artifact_corpus_scan_independently_rejects_known_sensitive_values() -> None:
    secret = "UNIQUE_SECRET_corpus_scan"
    artifacts = CompiledArtifacts.freeze(
        {
            "SKILL.md": secret,
            "skill.manifest.json": "{}",
            "skill.py": "pass\n",
            "browser_segment.py": "pass\n",
        }
    )

    issues = validate_artifacts(artifacts, forbidden_values=(secret,))

    assert any(issue.code == "artifact.sensitive_value" for issue in issues)


def test_cleanup_failure_rolls_back_old_publication_before_rejected_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline, definition = _payloads()
    destination = tmp_path / "skill"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("old-publication", encoding="utf-8")
    from rpa_agent.compiler import artifacts as artifact_module

    real_rmtree = artifact_module.shutil.rmtree

    def fail_backup_cleanup(path: object, *args: object, **kwargs: object) -> None:
        if ".backup-" in Path(path).name:
            raise OSError("injected backup cleanup failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(artifact_module.shutil, "rmtree", fail_backup_cleanup)

    result = DeterministicCompiler().compile(timeline, definition, destination)

    assert result.status == "rejected"
    assert result.artifacts is None
    assert any(issue.code == "artifact.publish_failed" for issue in result.issues)
    assert sentinel.read_text(encoding="utf-8") == "old-publication"
    assert sorted(path.name for path in destination.iterdir()) == ["sentinel.txt"]


def test_base_exception_during_backup_cleanup_restores_old_publication_then_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline, definition = _payloads()
    destination = tmp_path / "skill"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("old-publication", encoding="utf-8")
    from rpa_agent.compiler import artifacts as artifact_module

    real_rmtree = artifact_module.shutil.rmtree

    def interrupt_backup_cleanup(path: object, *args: object, **kwargs: object) -> None:
        if ".backup-" in Path(path).name:
            raise KeyboardInterrupt("injected cancellation")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(artifact_module.shutil, "rmtree", interrupt_backup_cleanup)

    with pytest.raises(KeyboardInterrupt, match="injected cancellation"):
        DeterministicCompiler().compile(timeline, definition, destination)

    assert sentinel.read_text(encoding="utf-8") == "old-publication"
    assert sorted(path.name for path in destination.iterdir()) == ["sentinel.txt"]


def test_task6_configuration_result_is_the_only_configuration_boundary_compiled(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    promotions = [
        {
            "trace_id": trace["trace_id"],
            "binding_name": binding["name"],
            "to_kind": "skill_input",
            "ref": binding["ref"],
        }
        for trace in timeline["traces"]
        for binding in trace["data_bindings"]
        if binding["kind"] == "skill_input"
    ]
    draft_payload = {
        "schema_version": "skill-configuration-draft/v0.1",
        "skill": {"name": definition["skill"]["name"], "description": definition["skill"]["description"]},
        "inputs": definition["inputs"],
        "secrets": definition["secrets"],
        "asset_inputs": definition["asset_inputs"],
        "outputs": definition["outputs"],
        "asset_outputs": definition["asset_outputs"],
        "binding_promotions": promotions,
        "stage_2_rules": definition["stage_2_rules"],
    }
    draft = SkillConfigurationDraft.model_validate(draft_payload)
    configured = transform_configuration(
        timeline,
        draft,
        skill_id=definition["skill"]["id"],
        skill_version=definition["skill"]["version"],
    )

    result = DeterministicCompiler().compile(
        configured.timeline,
        configured.skill_definition,
        tmp_path / "skill",
    )

    assert result.status == "published", result.issues
    assert set(result.artifacts.files) == {"SKILL.md", "skill.manifest.json", "skill.py", "browser_segment.py"}  # type: ignore[union-attr]

    valid_definition = configured.skill_definition
    for rejected_input in (draft, TraceCandidate.model_construct(), PageActivatedFact.model_construct()):
        rejected = DeterministicCompiler().compile(
            rejected_input,
            valid_definition,
            tmp_path / f"rejected-{type(rejected_input).__name__}",
        )
        assert rejected.status == "rejected"
        assert rejected.artifacts is None


@pytest.mark.parametrize(
    ("category", "expected_code"),
    [
        ("action", "action.invalid"),
        ("page", "page.not_introduced"),
        ("binding", "binding.required"),
        ("effect", "effect.navigation_redundant"),
        ("variable", "variable.unresolved"),
    ],
)
def test_semantic_negative_matrix_never_overwrites_old_publication(
    category: str,
    expected_code: str,
    tmp_path: Path,
) -> None:
    timeline, definition = _payloads()
    timeline = copy.deepcopy(timeline)
    if category == "action":
        timeline["traces"][1]["action"] = {"kind": "unsupported"}
    elif category == "page":
        timeline["traces"][0]["scope"]["page_ref"] = "not_introduced"
    elif category == "binding":
        timeline["traces"][0]["data_bindings"][0]["name"] = "wrong_slot"
    elif category == "effect":
        timeline["traces"][0]["effects"] = [{"kind": "navigation"}]
    else:
        timeline["traces"][10]["data_bindings"][0]["ref"] = "未生产变量.字段"
    destination = tmp_path / category
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("old", encoding="utf-8")

    result = DeterministicCompiler().compile(timeline, definition, destination)

    assert result.status == "rejected"
    assert result.artifacts is None
    assert any(issue.code == expected_code for issue in result.issues), result.issues
    assert sentinel.read_text(encoding="utf-8") == "old"
    assert sorted(path.name for path in destination.iterdir()) == ["sentinel.txt"]
