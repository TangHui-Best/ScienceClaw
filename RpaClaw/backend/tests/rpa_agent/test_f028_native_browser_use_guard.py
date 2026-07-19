from __future__ import annotations

import ast
from pathlib import Path


PRODUCTION_ROOT = Path(__file__).parents[2] / "rpa_agent"
FORBIDDEN_AGENT_KWARGS = {
    "tools",
    "controller",
    "max_actions_per_step",
    "max_history_items",
}
FORBIDDEN_CUSTOM_TOOL_NAMES = {
    "RecordingBrowserUseTools",
    "extract_variable_and_done",
}


def test_production_agent_construction_preserves_native_browser_use_defaults() -> None:
    violations: list[str] = []
    for path in PRODUCTION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in FORBIDDEN_CUSTOM_TOOL_NAMES:
                    violations.append(f"{path}:{node.lineno}:custom recording tool definition")
                continue
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if function_name in FORBIDDEN_CUSTOM_TOOL_NAMES:
                violations.append(f"{path}:{node.lineno}:custom recording tools")
            if function_name not in {"Agent", "agent_factory"}:
                continue
            forbidden = FORBIDDEN_AGENT_KWARGS & {
                keyword.arg for keyword in node.keywords if keyword.arg is not None
            }
            if forbidden:
                violations.append(
                    f"{path}:{node.lineno}:forbidden Agent kwargs {sorted(forbidden)}"
                )
    assert violations == []


def test_production_does_not_override_native_agent_step_budget() -> None:
    violations: list[str] = []
    for path in PRODUCTION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "run":
                continue
            if node.args or any(keyword.arg == "max_steps" for keyword in node.keywords):
                violations.append(f"{path}:{node.lineno}:Agent.run step budget override")
    assert violations == []
