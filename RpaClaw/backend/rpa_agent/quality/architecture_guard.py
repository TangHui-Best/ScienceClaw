"""Static dependency guard for the vNext platform and quality boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


_FORBIDDEN_ANYWHERE = ("backend.rpa", "rpa")
_FORBIDDEN_PLATFORM = ("backend.runtime.aio_runtime_provider",)
_FORBIDDEN_QUALITY = ("rpa_agent.creation", "rpa_agent.host", "rpa_agent.runtime")
_FORBIDDEN_NEXT_RUNTIME_PROVIDER = (
    "rpa_agent.creation",
    "rpa_agent.compiler",
    "rpa_agent.quality",
)


def find_next_architecture_violations(*roots: Path) -> list[str]:
    violations: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            relative = path.name if root.is_file() else path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = _imported_module(node)
                if module is None:
                    continue
                forbidden = _forbidden_for(relative, module)
                if forbidden is not None:
                    violations.append(
                        f"{relative}:{node.lineno}: forbidden import '{forbidden}'"
                    )
    return violations


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name if node.names else None
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None


def _forbidden_for(relative: str, module: str) -> str | None:
    if module == "rpa" or module.startswith("backend.rpa"):
        return "backend.rpa"
    if relative.startswith("platform/") and module.startswith(_FORBIDDEN_PLATFORM):
        return _FORBIDDEN_PLATFORM[0]
    if relative.startswith("quality/"):
        for forbidden in _FORBIDDEN_QUALITY:
            if module.startswith(forbidden):
                return forbidden
    if relative.endswith("rpa_agent_next_aio_provider.py"):
        for forbidden in _FORBIDDEN_NEXT_RUNTIME_PROVIDER:
            if module.startswith(forbidden):
                return forbidden
    return None
