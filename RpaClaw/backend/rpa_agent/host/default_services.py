"""默认 SKILL 测试运行与发布宿主。

只消费编译产物和已校验 SkillDefinition，不读取 Candidate、BrowserFact、
Browser-use History 或旧 RPA 数据结构。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import secrets
import shutil
import sys
from types import ModuleType
from typing import Awaitable, Callable, Mapping

from ..api import TestRunRequest
from ..runtime import DataAssetHandle, RunContext, SkillRunResult, StepExecutionError


_REQUIRED_FILES = frozenset(
    {"SKILL.md", "skill.manifest.json", "skill.py", "browser_segment.py"}
)


async def run_compiled_skill(
    hosted: object,
    request: TestRunRequest,
    *,
    agent_backend: Callable[..., Awaitable[Mapping[str, object]]] | None = None,
) -> dict[str, object]:
    configuration = getattr(hosted, "configuration", None)
    definition = getattr(configuration, "skill_definition", None)
    if definition is None:
        raise ValueError("runtime.skill_definition_missing")
    artifact_dir = Path(getattr(hosted, "artifact_dir"))
    _validate_artifact_files(artifact_dir)
    package_name = "rpa_generated_" + secrets.token_hex(12)
    run_id = "run_" + secrets.token_hex(12)

    async def secret_provider(ref: str) -> str | None:
        return request.secrets.get(ref)

    assets = {
        ref: DataAssetHandle(ref=ref, runtime_value=value)
        for ref, value in request.data_assets.items()
    }
    module = _load_generated_package(artifact_dir, package_name)
    try:
        context = RunContext(
            run_id=run_id,
            definition=definition,
            main_page=getattr(getattr(hosted, "browser"), "main_page"),
            input_values=request.inputs,
            secret_provider=secret_provider,
            asset_inputs=assets,
            agent_backend=agent_backend,
        )
        result = await module.execute_skill(context)
        if not isinstance(result, SkillRunResult):
            raise ValueError("runtime.skill_result_invalid")
        return result.to_dict()
    except StepExecutionError as exc:
        return {
            "run_id": run_id,
            "status": "failed",
            "outputs": {},
            "data_assets": {},
            "steps": [],
            "error": {
                "trace_id": exc.trace_id,
                "sequence": exc.sequence,
                "action_kind": exc.action_kind,
                "phase": exc.phase,
                "code": exc.code,
                "message": exc.safe_message,
            },
        }
    finally:
        _cleanup_generated_package(package_name)


async def publish_compiled_skill(
    hosted: object,
    *,
    destination_root: Path,
) -> dict[str, str]:
    configuration = getattr(hosted, "configuration", None)
    definition = getattr(configuration, "skill_definition", None)
    if definition is None:
        raise ValueError("publisher.skill_definition_missing")
    skill_id = definition.skill.id
    source = Path(getattr(hosted, "artifact_dir"))
    _validate_artifact_files(source, code_prefix="publisher")
    root = destination_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / skill_id).resolve()
    if target.parent != root:
        raise ValueError("publisher.target_invalid")
    if target.exists():
        raise ValueError("publisher.target_exists")
    temporary = root / (".publish-" + secrets.token_hex(12))
    temporary.mkdir()
    try:
        for name in sorted(_REQUIRED_FILES):
            shutil.copyfile(source / name, temporary / name)
        os.replace(temporary, target)
    finally:
        if temporary.exists() and temporary.parent == root:
            shutil.rmtree(temporary)
    await asyncio.sleep(0)
    return {"skill_ref": f"external:{skill_id}"}


def _validate_artifact_files(path: Path, *, code_prefix: str = "runtime") -> None:
    for name in _REQUIRED_FILES:
        item = path / name
        if not item.is_file() or item.is_symlink():
            raise ValueError(f"{code_prefix}.artifact_invalid:{name}")


def _load_generated_package(path: Path, package_name: str) -> ModuleType:
    package = ModuleType(package_name)
    package.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[package_name] = package
    canonical_root_name = __package__.rsplit(".", 1)[0]
    canonical_runtime_name = f"{canonical_root_name}.runtime"
    canonical_root = sys.modules[canonical_root_name]
    canonical_runtime = sys.modules[canonical_runtime_name]
    missing = object()
    previous_aliases = {
        "rpa_agent": sys.modules.get("rpa_agent", missing),
        "rpa_agent.runtime": sys.modules.get("rpa_agent.runtime", missing),
    }
    # Compiled artifacts intentionally depend on the public ``rpa_agent``
    # runtime name. The local service is launched as ``backend.main``, so expose
    # that public name only while importing the artifact and keep class identity
    # aligned with the already-loaded host runtime.
    sys.modules["rpa_agent"] = canonical_root
    sys.modules["rpa_agent.runtime"] = canonical_runtime
    try:
        for module_name in ("browser_segment", "skill"):
            spec = importlib.util.spec_from_file_location(
                f"{package_name}.{module_name}", path / f"{module_name}.py"
            )
            if spec is None or spec.loader is None:
                raise ValueError("runtime.artifact_import_invalid")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        return sys.modules[f"{package_name}.skill"]
    except BaseException:
        _cleanup_generated_package(package_name)
        raise
    finally:
        for alias, previous in previous_aliases.items():
            if previous is missing:
                sys.modules.pop(alias, None)
            else:
                sys.modules[alias] = previous


def _cleanup_generated_package(package_name: str) -> None:
    for name in (
        f"{package_name}.skill",
        f"{package_name}.browser_segment",
        package_name,
    ):
        sys.modules.pop(name, None)


__all__ = ["publish_compiled_skill", "run_compiled_skill"]
