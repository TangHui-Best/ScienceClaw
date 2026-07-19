"""四文件 SKILL 的渲染、静态验证与原子发布。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from types import MappingProxyType
from typing import Mapping

from ..contracts import SkillManifest
from .plan import BrowserCompilePlan, CompileIssue
from .renderers import binding_expression, render_action, render_outputs


ARTIFACT_NAMES = frozenset(
    {"SKILL.md", "skill.manifest.json", "skill.py", "browser_segment.py"}
)


@dataclass(frozen=True, slots=True)
class CompiledArtifacts:
    files: Mapping[str, str]

    @classmethod
    def freeze(cls, files: dict[str, str]) -> "CompiledArtifacts":
        return cls(files=MappingProxyType(dict(files)))


def _indent(lines: list[str], spaces: int = 4) -> list[str]:
    prefix = " " * spaces
    return [prefix + line if line else "" for line in lines]


def _binding_by_name(trace: object, name: str) -> object:
    return next(item for item in trace.data_bindings if item.name == name)


def _target_lines(trace: object) -> list[str]:
    target = getattr(trace.action, "target", None)
    if target is None:
        return []
    target_payload = target.model_dump(mode="python", exclude_none=True)
    lines = [f"target_spec = {target_payload!r}"]
    for index, step in enumerate(target.path or []):
        if step.filter_binding is None:
            continue
        expression = binding_expression(_binding_by_name(trace, step.filter_binding))
        lines.extend(
            [
                f"target_spec['path'][{index}].pop('filter_binding', None)",
                f"target_spec['path'][{index}]['filter_text'] = str({expression})",
            ]
        )
    lines.append("target = await ctx.locators.resolve(scope=scope, target=target_spec)")
    return lines


def _effect_lines(trace: object) -> tuple[list[str], list[str]]:
    if not trace.effects:
        return [], []
    effects = []
    for effect in trace.effects:
        payload = effect.model_dump(mode="python", exclude_none=True)
        if effect.kind == "download":
            binding = _binding_by_name(trace, effect.binding)
            payload["asset_ref"] = binding.ref
        effects.append(payload)
    prepare = [f"effect_specs = {effects!r}"]
    for index, effect in enumerate(trace.effects):
        if effect.kind == "dialog" and effect.input_binding is not None:
            expression = binding_expression(_binding_by_name(trace, effect.input_binding))
            prepare.append(f"effect_specs[{index}].pop('input_binding', None)")
            prepare.append(f"effect_specs[{index}]['input_value'] = {expression}")
    prepare.append("effect_handle = await ctx.effects.prepare(scope=scope, effects=effect_specs)")
    return prepare, ["await ctx.effects.commit(effect_handle)"]


def _wait_lines(trace: object) -> list[str]:
    if not trace.wait_until:
        return []
    conditions = [condition.model_dump(mode="python", exclude_none=True) for condition in trace.wait_until]
    new_page = next((effect for effect in trace.effects if effect.kind == "new_page"), None)
    if new_page is None:
        lines = ["wait_scope = scope", f"wait_conditions = {conditions!r}"]
    else:
        lines = [
            f"wait_page = ctx.pages.require({new_page.page_ref!r})",
            "wait_scope = await ctx.frames.resolve(wait_page, [])",
            f"wait_conditions = {conditions!r}",
        ]
    for index, condition in enumerate(trace.wait_until):
        expected_binding = getattr(condition, "expected_binding", None)
        if expected_binding is None:
            continue
        expression = binding_expression(_binding_by_name(trace, expected_binding))
        lines.extend(
            [
                f"wait_conditions[{index}].pop('expected_binding', None)",
                f"wait_conditions[{index}]['expected'] = {expression}",
            ]
        )
    lines.append("await ctx.waits.until(scope=wait_scope, conditions=wait_conditions)")
    return lines


def _render_step(trace: object, plan: BrowserCompilePlan) -> str:
    function_name = f"step_{trace.sequence:03d}_{trace.action.kind}"
    body = [
        f"page = ctx.pages.require({trace.scope.page_ref!r})",
        "scope = await ctx.frames.resolve(page, "
        f"{[step.model_dump(mode='python') for step in trace.scope.frame_path]!r})",
    ]
    body.extend(_target_lines(trace))
    prepare, commit = _effect_lines(trace)
    body.extend(prepare)
    body.extend(render_action(trace, plan))
    body.extend(commit)
    body.extend(render_outputs(trace))
    body.extend(_wait_lines(trace))
    return "\n".join(
        [
            f"async def {function_name}(ctx: RunContext) -> None:",
            *_indent(body),
            "",
        ]
    )


def render_browser_segment(plan: BrowserCompilePlan) -> str:
    header = """from __future__ import annotations

from collections.abc import Awaitable, Callable

from rpa_agent.runtime import RunContext


async def _run_step(
    ctx: RunContext,
    *,
    trace_id: str,
    sequence: int,
    action_kind: str,
    operation: Callable[[], Awaitable[None]],
) -> None:
    await ctx.steps.execute(
        trace_id=trace_id,
        sequence=sequence,
        action_kind=action_kind,
        operation=operation,
    )

"""
    steps = "\n".join(_render_step(trace, plan) for trace in plan.timeline.traces)
    run_lines = [
        "async def run_browser_segment(ctx: RunContext) -> None:",
        "    \"\"\"按 CoreTrace sequence 顺序执行确定性浏览器段。\"\"\"",
    ]
    if not plan.timeline.traces:
        run_lines.append("    return None")
    for trace in plan.timeline.traces:
        function_name = f"step_{trace.sequence:03d}_{trace.action.kind}"
        run_lines.extend(
            [
                "    await _run_step(",
                "        ctx,",
                f"        trace_id={trace.trace_id!r},",
                f"        sequence={trace.sequence},",
                f"        action_kind={trace.action.kind!r},",
                f"        operation=lambda: {function_name}(ctx),",
                "    )",
            ]
        )
    return header + steps + "\n".join(run_lines) + "\n"


def render_skill_entrypoint(plan: BrowserCompilePlan) -> str:
    output_refs = tuple(item.variable_ref for item in plan.definition.outputs)
    asset_refs = tuple(item.asset_ref for item in plan.definition.asset_outputs)
    return f'''from __future__ import annotations

from rpa_agent.runtime import RunContext, SkillRunResult

from .browser_segment import run_browser_segment


async def execute_skill(ctx: RunContext) -> SkillRunResult:
    await run_browser_segment(ctx)
    return ctx.results.succeeded(
        outputs=ctx.variables.export({output_refs!r}),
        data_assets=ctx.assets.export({asset_refs!r}),
    )
'''


def render_skill_markdown(plan: BrowserCompilePlan) -> str:
    definition = plan.definition
    inputs = "\n".join(
        f"- `{item.ref}`：{item.title}（{'必填' if item.required else '可选'}）"
        for item in definition.inputs
    ) or "- 无"
    secrets = "\n".join(f"- `{item.ref}`：{item.title}" for item in definition.secrets) or "- 无"
    outputs = "\n".join(
        f"- `{item.name}` ← `{item.variable_ref}`：{item.title}" for item in definition.outputs
    ) or "- 无"
    stage_2 = definition.stage_2_rules or "无。"
    return f"""# {definition.skill.name}

{definition.skill.description}

## 输入

{inputs}

## Secret

{secrets}

## 阶段一浏览器流程

按已确认的 {len(plan.timeline.traces)} 条 CoreTrace 顺序执行；任一步骤失败立即停止，不跳过、不自动改用 Agent。

## 阶段二自然语言规则

{stage_2}

## 声明输出

{outputs}

## 失败边界

不读取录制值，不补造 Locator，不自动重试整条 SKILL；运行错误由宿主按 trace_id、sequence 和 phase 返回。
"""


def render_artifacts(plan: BrowserCompilePlan) -> CompiledArtifacts:
    files = {
        "SKILL.md": render_skill_markdown(plan),
        "skill.manifest.json": json.dumps(
            plan.manifest.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        "skill.py": render_skill_entrypoint(plan),
        "browser_segment.py": render_browser_segment(plan),
    }
    return CompiledArtifacts.freeze(files)


def validate_artifacts(
    artifacts: CompiledArtifacts,
    *,
    forbidden_values: tuple[str, ...] = (),
) -> list[CompileIssue]:
    issues: list[CompileIssue] = []
    if set(artifacts.files) != ARTIFACT_NAMES:
        issues.append(CompileIssue("artifact.file_set", "产物文件集合必须恰为四文件", None, None, "artifacts"))
        return issues
    for name in ("skill.py", "browser_segment.py"):
        try:
            ast.parse(artifacts.files[name], filename=name)
        except SyntaxError as exc:
            issues.append(CompileIssue("artifact.python_syntax", str(exc), None, None, name))
    try:
        SkillManifest.model_validate(json.loads(artifacts.files["skill.manifest.json"]))
    except Exception as exc:
        issues.append(CompileIssue("artifact.manifest_schema", str(exc), None, None, "skill.manifest.json"))
    corpus = "\n".join(artifacts.files.values()).lower()
    original_corpus = "\n".join(artifacts.files.values())
    for value in forbidden_values:
        if value and value in original_corpus:
            issues.append(
                CompileIssue(
                    "artifact.sensitive_value",
                    "产物包含禁止持久化的敏感值",
                    None,
                    None,
                    "artifacts",
                )
            )
    forbidden = {
        ".first(": "artifact.locator_first",
        "exec(": "artifact.exec",
        "sleep(": "artifact.fixed_sleep",
        "backend.rpa": "artifact.legacy_dependency",
        "tracecandidate": "artifact.creation_dependency",
        "browserfact": "artifact.creation_dependency",
    }
    for needle, code in forbidden.items():
        if needle in corpus:
            issues.append(CompileIssue(code, f"产物包含禁止内容：{needle}", None, None, "artifacts"))
    if re.search(r"[A-Za-z]:\\\\", corpus):
        issues.append(CompileIssue("artifact.absolute_path", "产物包含本地绝对路径", None, None, "artifacts"))
    return issues


def _has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    return any(component.is_symlink() for component in (absolute, *absolute.parents))


def _rollback_after_cleanup_failure(
    *,
    destination: Path,
    backup: Path,
    parent: Path,
) -> bool:
    """Restore the old directory after the new directory was already swapped in.

    ``False`` means rollback itself could not complete and the new publication
    was restored/left active; callers must not report ``rejected`` in that case.
    """

    quarantine = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.rollback-", dir=parent)
    )
    quarantine.rmdir()
    try:
        os.replace(destination, quarantine)
        try:
            os.replace(backup, destination)
        except BaseException:
            if not destination.exists() and quarantine.exists():
                os.replace(quarantine, destination)
            raise
    except Exception:
        return False
    try:
        shutil.rmtree(quarantine)
    except BaseException:
        # The authoritative destination is already restored.  Orphan cleanup
        # must never mask the original cleanup failure or change its status.
        pass
    return True


def publish_artifacts(artifacts: CompiledArtifacts, destination: Path) -> CompileIssue | None:
    destination = destination.absolute()
    if destination.name in {"", ".", ".."} or _has_symlink_component(destination):
        return CompileIssue("artifact.path_unsafe", "发布目录包含符号链接或非法路径", None, None, "destination")
    if destination.exists() and not destination.is_dir():
        return CompileIssue("artifact.path_unsafe", "发布目标不是目录", None, None, "destination")
    parent = destination.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        if _has_symlink_component(parent):
            return CompileIssue("artifact.path_unsafe", "发布父目录包含符号链接", None, None, "destination")
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=parent))
        for name, content in artifacts.files.items():
            target = temporary / name
            if target.parent != temporary or name not in ARTIFACT_NAMES:
                raise ValueError("artifact.path_escape")
            target.write_text(content, encoding="utf-8", newline="\n")
        backup: Path | None = None
        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}.backup-", dir=parent))
            backup.rmdir()
            os.replace(destination, backup)
        try:
            os.replace(temporary, destination)
        except BaseException:
            if backup is not None and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise
        if backup is not None and backup.exists():
            try:
                shutil.rmtree(backup)
            except BaseException as cleanup_error:
                restored = _rollback_after_cleanup_failure(
                    destination=destination,
                    backup=backup,
                    parent=parent,
                )
                if not restored:
                    # The atomic swap remains a valid publication.  Reporting
                    # rejected here would lie about the active destination.
                    return None
                if isinstance(cleanup_error, Exception):
                    return CompileIssue(
                        "artifact.publish_failed",
                        str(cleanup_error),
                        None,
                        None,
                        "destination",
                    )
                raise
        return None
    except Exception as exc:
        if "temporary" in locals() and temporary.exists():
            shutil.rmtree(temporary)
        return CompileIssue("artifact.publish_failed", str(exc), None, None, "destination")
