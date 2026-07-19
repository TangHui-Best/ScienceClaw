from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from rpa_agent.compiler import DeterministicCompiler


EXAMPLE = Path(__file__).parents[1] / "contracts" / "golden" / "first_e2e"


def _payloads() -> tuple[dict, dict]:
    return (
        json.loads((EXAMPLE / "coretrace.timeline.json").read_text(encoding="utf-8")),
        json.loads((EXAMPLE / "skill.definition.json").read_text(encoding="utf-8")),
    )


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_golden_24_trace_compiles_to_exactly_four_atomic_artifacts(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    destination = tmp_path / "purchase-order-acceptance"

    result = DeterministicCompiler().compile(timeline, definition, destination)

    assert result.status == "published", result.issues
    assert result.artifacts is not None
    expected_names = {"SKILL.md", "skill.manifest.json", "skill.py", "browser_segment.py"}
    assert set(result.artifacts.files) == expected_names
    assert {path.name for path in destination.iterdir()} == expected_names
    assert all(path.is_file() and not path.is_symlink() for path in destination.iterdir())


def test_golden_has_one_named_step_per_trace_and_original_sequence_calls(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    destination = tmp_path / "skill"
    result = DeterministicCompiler().compile(timeline, definition, destination)
    source = result.artifacts.files["browser_segment.py"]  # type: ignore[union-attr]
    tree = ast.parse(source)

    step_functions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and re.fullmatch(r"step_\d{3}_[a-z_]+", node.name)
    ]
    assert len(step_functions) == len(timeline["traces"]) == 24
    assert step_functions == [
        f"step_{trace['sequence']:03d}_{trace['action']['kind']}"
        for trace in timeline["traces"]
    ]

    run_function = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_browser_segment"
    )
    run_source = ast.get_source_segment(source, run_function) or ""
    positions = [run_source.index(f"step_{trace['sequence']:03d}_{trace['action']['kind']}") for trace in timeline["traces"]]
    assert positions == sorted(positions)


def test_manifest_is_exact_definition_projection_with_canonical_source(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    result = DeterministicCompiler(compiler_version="rpa-agent-compiler/0.1").compile(
        timeline,
        definition,
        tmp_path / "skill",
    )
    manifest = json.loads(result.artifacts.files["skill.manifest.json"])  # type: ignore[union-attr]

    for field in ("skill", "inputs", "secrets", "asset_inputs", "outputs", "asset_outputs"):
        assert manifest[field] == definition[field]
    assert manifest["entrypoint"] == "skill:execute_skill"
    assert manifest["runtime"]["api_version"] == "rpa-agent-runtime/0.1"
    assert manifest["runtime"]["requirements"] == ["playwright", "agent"]
    assert manifest["source"] == {
        "core_trace_schema_version": "core-trace/v0.1",
        "trace_count": 24,
        "timeline_hash": _canonical_hash(timeline),
        "compiler_version": "rpa-agent-compiler/0.1",
    }


def test_generated_python_is_ast_valid_and_has_no_forbidden_execution_shortcuts(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    result = DeterministicCompiler().compile(timeline, definition, tmp_path / "skill")

    for name in ("skill.py", "browser_segment.py"):
        source = result.artifacts.files[name]  # type: ignore[union-attr]
        ast.parse(source)
        lowered = source.lower()
        assert ".first(" not in lowered
        assert "exec(" not in lowered
        assert "sleep(" not in lowered
        assert "browser-use" not in lowered
        assert "tracecandidate" not in lowered
        assert "browserfact" not in lowered
        assert "history" not in lowered
        assert "backend.rpa" not in lowered
        assert "FrameStep(" not in source
        assert "TargetSpec(" not in source
        assert "RoleLocator(" not in source


def test_golden_bindings_effects_and_agent_are_rendered_through_controlled_runtime(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    result = DeterministicCompiler().compile(timeline, definition, tmp_path / "skill")
    source = result.artifacts.files["browser_segment.py"]  # type: ignore[union-attr]

    assert "ctx.inputs.require('query.order_no')" in source
    assert "ctx.variables.require('采购订单.订单号')" in source
    assert "ctx.variables.write('采购订单'," in source
    assert "ctx.pages.require('main')" in source
    assert "ctx.frames.resolve(" in source
    assert "ctx.locators.resolve(" in source
    assert "ctx.effects.prepare(" in source
    assert "ctx.effects.commit(" in source
    assert "ctx.agent.execute(" in source
    assert "required_paths=" in source
    assert source.index("ctx.effects.prepare(") < source.index("await target.click()", source.index("ctx.effects.prepare("))
    assert source.index("ctx.effects.commit(") > source.index("await target.click()", source.index("ctx.effects.prepare("))
    step_100 = source[source.index("async def step_100_click"):source.index("async def step_110_fill")]
    assert step_100.index("ctx.effects.commit(") < step_100.index("ctx.pages.require('acceptance_detail')")
    assert "ctx.waits.until(scope=wait_scope" in step_100


def test_artifacts_do_not_embed_replay_values_random_urls_tokens_or_runtime_ids(tmp_path: Path) -> None:
    timeline, definition = _payloads()
    replay_a = (EXAMPLE / "replay-a.inputs.json").read_text(encoding="utf-8")
    replay_b = (EXAMPLE / "replay-b.inputs.json").read_text(encoding="utf-8")
    result = DeterministicCompiler().compile(timeline, definition, tmp_path / "skill")
    corpus = "\n".join(result.artifacts.files.values())  # type: ignore[union-attr]

    for payload in (json.loads(replay_a), json.loads(replay_b)):
        for value in payload["inputs"].values():
            assert str(value) not in corpus
    forbidden_patterns = (
        r"https?://[^\s'\"]+[?&](?:token|task_id)=",
        r"\b(?:tab_id|target_id|frame_id|page_id|dom_index)\b",
        r"[A-Za-z]:\\",
    )
    assert not any(re.search(pattern, corpus, flags=re.IGNORECASE) for pattern in forbidden_patterns)
