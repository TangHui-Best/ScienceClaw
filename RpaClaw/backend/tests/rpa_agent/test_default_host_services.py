from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType

import pytest

from rpa_agent.host import default_services
from rpa_agent.api import TestRunRequest as ApiTestRunRequest
from rpa_agent.contracts import SkillDefinition
from rpa_agent.host.default_services import publish_compiled_skill, run_compiled_skill


REQUIRED = {"SKILL.md", "skill.manifest.json", "skill.py", "browser_segment.py"}


def test_generated_runtime_imports_are_aliased_without_duplicate_class_identity(
    monkeypatch,
) -> None:
    prefix = "backend_topology.rpa_agent"
    source_modules = {
        prefix: ModuleType(prefix),
        f"{prefix}.runtime": ModuleType(f"{prefix}.runtime"),
        f"{prefix}.runtime.results": ModuleType(f"{prefix}.runtime.results"),
    }
    aliases = {
        "rpa_agent": source_modules[prefix],
        "rpa_agent.runtime": source_modules[f"{prefix}.runtime"],
        "rpa_agent.runtime.results": source_modules[f"{prefix}.runtime.results"],
    }
    originals = {name: sys.modules.get(name) for name in aliases}
    monkeypatch.setattr(default_services, "__package__", f"{prefix}.host")
    try:
        for name, module in source_modules.items():
            sys.modules[name] = module
        for name in aliases:
            sys.modules.pop(name, None)

        default_services._ensure_public_runtime_aliases()

        assert {name: sys.modules[name] for name in aliases} == aliases
    finally:
        for name in (*aliases, *source_modules):
            sys.modules.pop(name, None)
        for name, module in originals.items():
            if module is not None:
                sys.modules[name] = module


def _definition() -> SkillDefinition:
    return SkillDefinition.model_validate(
        {
            "schema_version": "skill-definition/v0.1",
            "skill": {
                "id": "purchase-order-acceptance",
                "name": "采购订单验收",
                "version": "0.1.0",
                "description": "真实浏览器纵向回放",
            },
            "inputs": [],
            "secrets": [],
            "asset_inputs": [],
            "outputs": [],
            "asset_outputs": [],
            "stage_2_rules": None,
        }
    )


@dataclass
class _Configuration:
    skill_definition: SkillDefinition


@dataclass
class _Browser:
    main_page: object


@dataclass
class _Hosted:
    session_id: str
    artifact_dir: Path
    configuration: _Configuration
    browser: _Browser


def _hosted(tmp_path: Path, *, skill_source: str) -> _Hosted:
    artifact = tmp_path / "artifact"
    artifact.mkdir(parents=True)
    (artifact / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (artifact / "skill.manifest.json").write_text("{}", encoding="utf-8")
    (artifact / "browser_segment.py").write_text("VALUE = 1\n", encoding="utf-8")
    (artifact / "skill.py").write_text(skill_source, encoding="utf-8")
    return _Hosted(
        session_id="rca_abcdefghijklmnopqrstuvwx",
        artifact_dir=artifact,
        configuration=_Configuration(_definition()),
        browser=_Browser(object()),
    )


@pytest.mark.asyncio
async def test_default_runner_loads_exact_compiled_package_and_cleans_modules(tmp_path: Path) -> None:
    hosted = _hosted(
        tmp_path,
        skill_source=(
            "from .browser_segment import VALUE\n"
            "async def execute_skill(ctx):\n"
            "    assert VALUE == 1\n"
            "    return ctx.results.succeeded(outputs={}, data_assets={})\n"
        ),
    )
    result = await run_compiled_skill(
        hosted,
        ApiTestRunRequest.model_validate({"inputs": {}, "secrets": {}, "data_assets": {}}),
    )
    assert result == {
        "run_id": result["run_id"],
        "status": "succeeded",
        "outputs": {},
        "data_assets": {},
        "steps": [],
        "error": None,
    }
    assert result["run_id"].startswith("run_")


@pytest.mark.asyncio
async def test_default_runner_returns_structured_failed_step_without_secret_leak(tmp_path: Path) -> None:
    hosted = _hosted(
        tmp_path,
        skill_source=(
            "from rpa_agent.runtime.results import StepExecutionError\n"
            "async def execute_skill(ctx):\n"
            "    raise StepExecutionError(run_id=ctx.run_id, trace_id='trace_1', sequence=1, "
            "action_kind='click', phase='action', code='target.ambiguous', safe_message='目标不唯一')\n"
        ),
    )
    result = await run_compiled_skill(
        hosted,
        ApiTestRunRequest.model_validate({"inputs": {}, "secrets": {"password": "TOPSECRET"}, "data_assets": {}}),
    )
    assert result["status"] == "failed"
    assert result["error"] == {
        "trace_id": "trace_1",
        "sequence": 1,
        "action_kind": "click",
        "phase": "action",
        "code": "target.ambiguous",
        "message": "目标不唯一",
    }
    assert "TOPSECRET" not in str(result)


@pytest.mark.asyncio
async def test_default_publisher_atomically_publishes_only_four_files(tmp_path: Path) -> None:
    hosted = _hosted(tmp_path, skill_source="async def execute_skill(ctx): pass\n")
    (hosted.artifact_dir / "__pycache__").mkdir()
    (hosted.artifact_dir / "ignored.log").write_text("not published", encoding="utf-8")
    root = tmp_path / "published"
    result = await publish_compiled_skill(hosted, destination_root=root)
    target = root / "purchase-order-acceptance"
    assert result == {"skill_ref": "external:purchase-order-acceptance"}
    assert {item.name for item in target.iterdir()} == REQUIRED
    assert not list(root.glob(".publish-*"))


@pytest.mark.asyncio
async def test_default_publisher_refuses_overwrite_and_symlink(tmp_path: Path) -> None:
    hosted = _hosted(tmp_path, skill_source="async def execute_skill(ctx): pass\n")
    root = tmp_path / "published"
    root.mkdir()
    (root / "purchase-order-acceptance").mkdir()
    with pytest.raises(ValueError, match="publisher.target_exists"):
        await publish_compiled_skill(hosted, destination_root=root)

    link_hosted = _hosted(tmp_path / "other", skill_source="async def execute_skill(ctx): pass\n")
    (link_hosted.artifact_dir / "SKILL.md").unlink()
    try:
        (link_hosted.artifact_dir / "SKILL.md").symlink_to(link_hosted.artifact_dir / "skill.py")
    except OSError:
        pytest.skip("current platform cannot create symlinks")
    with pytest.raises(ValueError, match="publisher.artifact_invalid"):
        await publish_compiled_skill(link_hosted, destination_root=tmp_path / "other-published")
