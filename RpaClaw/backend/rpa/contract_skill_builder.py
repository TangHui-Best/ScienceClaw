from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from textwrap import indent
from typing import Any, Dict, Iterable, List

from .contract_models import ArtifactKind
from .contract_pipeline import CommittedStep


def build_contract_skill_files(
    skill_name: str,
    description: str,
    committed_steps: List[CommittedStep],
) -> Dict[str, str]:
    manifest = _build_manifest(skill_name, description, committed_steps)
    skill_py = _build_skill_py(committed_steps)
    skill_md = _build_skill_md(skill_name, description)
    return {
        "SKILL.md": skill_md,
        "skill.py": skill_py,
        "skill.contract.json": json.dumps(manifest, ensure_ascii=False, indent=2),
    }


def write_contract_skill(
    skill_dir: Path,
    skill_name: str,
    description: str,
    committed_steps: List[CommittedStep],
) -> Dict[str, str]:
    files = build_contract_skill_files(skill_name, description, committed_steps)
    skill_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (skill_dir / filename).write_text(content, encoding="utf-8")
    return files


def _build_skill_md(skill_name: str, description: str) -> str:
    return f"""---
name: {skill_name}
description: {description}
---

# {skill_name}

{description}

This RPA skill is generated from committed contract-first artifacts.
"""


def _build_manifest(
    skill_name: str,
    description: str,
    committed_steps: List[CommittedStep],
) -> Dict[str, Any]:
    blackboard_schema: Dict[str, Any] = {}
    steps = []

    for step in committed_steps:
        contract = step.contract
        if contract.outputs.blackboard_key:
            blackboard_schema[contract.outputs.blackboard_key] = contract.outputs.schema_value
        for ref in contract.inputs.refs:
            if isinstance(ref, str) and ref and not ref.startswith("params."):
                blackboard_schema.setdefault(ref.split(".", 1)[0], {"type": "unknown"})

        steps.append(
            {
                "contract_id": contract.id,
                "input_refs": list(contract.inputs.refs),
                "contract": _jsonable(contract.model_dump(by_alias=True)),
                "artifact": _jsonable(step.artifact),
                "validation_evidence": _jsonable(step.validation_evidence),
            }
        )

    return {
        "schema_version": "rpa.contract.v1",
        "name": skill_name,
        "description": description,
        "blackboard_schema": _jsonable(blackboard_schema),
        "steps": steps,
    }


def _build_skill_py(committed_steps: List[CommittedStep]) -> str:
    uses_runtime_ai = any(_artifact_kind(step.artifact) == ArtifactKind.RUNTIME_AI.value for step in committed_steps)
    imports = [
        "import asyncio",
        "import json as _json",
        "import re",
        "import sys",
        "from dataclasses import dataclass, field",
        "from typing import Any, Dict",
        "from playwright.async_api import async_playwright",
    ]
    if uses_runtime_ai:
        imports.append("from backend.rpa.runtime_ai_instruction import execute_ai_instruction")

    body = "\n".join(imports)
    body += "\n\n\n"
    body += _BLACKBOARD_RUNTIME
    body += "\n\n\nasync def execute_skill(page, **kwargs):\n"
    body += "    board = Blackboard(runtime_params=kwargs)\n"
    body += "    current_page = page\n"

    for index, step in enumerate(committed_steps):
        body += _render_step(index, step)

    body += "    return board.values\n"
    body += _MAIN_RUNTIME
    return body


def _render_step(index: int, step: CommittedStep) -> str:
    artifact = step.artifact
    kind = _artifact_kind(artifact)
    lines = [f"\n    # step {index}: {step.contract.id}\n"]

    if kind == ArtifactKind.PRIMITIVE_ACTION.value:
        action = artifact.get("action")
        if action == "goto":
            template = artifact.get("target_url_template") or step.contract.target.url_template
            lines.append(f"    _target_url = resolve_template({template!r}, board)\n")
            lines.append("    await current_page.goto(_target_url, wait_until='domcontentloaded')\n")
            lines.append("    await current_page.wait_for_load_state('domcontentloaded')\n")
        elif action == "click":
            lines.append(f"    _locator = locator_from_payload(current_page, {_jsonable_repr(artifact.get('locator'))})\n")
            lines.append("    await _locator.click()\n")
        elif action == "fill":
            lines.append(f"    _locator = locator_from_payload(current_page, {_jsonable_repr(artifact.get('locator'))})\n")
            lines.append(f"    _value = resolve_template({artifact.get('value_template', '')!r}, board)\n")
            lines.append("    await _locator.fill(_value)\n")
        elif action == "extract_text":
            result_key = artifact.get("result_key") or step.contract.outputs.blackboard_key
            lines.append(f"    _locator = locator_from_payload(current_page, {_jsonable_repr(artifact.get('locator'))})\n")
            lines.append("    _text = await _locator.inner_text()\n")
            if result_key:
                lines.append(f"    board.write({result_key!r}, _text)\n")
        else:
            lines.append(f"    raise RuntimeError('Unsupported primitive action: {action}')\n")

    elif kind == ArtifactKind.DETERMINISTIC_SCRIPT.value:
        code = str(artifact.get("code") or "")
        result_key = artifact.get("result_key") or step.contract.outputs.blackboard_key
        lines.append(indent(code, "    "))
        lines.append("\n")
        lines.append("    _result = await run(current_page, board)\n")
        if result_key:
            lines.append(f"    board.write({result_key!r}, _result)\n")

    elif kind == ArtifactKind.RUNTIME_AI.value:
        result_key = artifact.get("result_key") or step.contract.outputs.blackboard_key
        step_payload = {
            "action": "ai_instruction",
            "description": artifact.get("description", ""),
            "prompt": artifact.get("prompt", ""),
            "instruction_kind": artifact.get("instruction_kind", "runtime_semantic"),
            "input_scope": artifact.get("input_scope", {"mode": "current_page"}),
            "output_expectation": {"mode": "extract", "schema": artifact.get("output_schema")},
            "execution_hint": {"requires_dom_snapshot": True, "allow_navigation": artifact.get("allow_side_effect", False)},
            "result_key": result_key,
        }
        lines.append(f"    _runtime_step = _json.loads({_jsonable_json(step_payload)!r})\n")
        lines.append("    _result = await execute_ai_instruction(current_page, step=_runtime_step, results=board.values)\n")
        if result_key:
            lines.append(f"    board.write({result_key!r}, _result.get('output') if isinstance(_result, dict) and 'output' in _result else _result)\n")
    else:
        lines.append(f"    raise RuntimeError('Unsupported artifact kind: {kind}')\n")

    return "".join(lines)


def _artifact_kind(artifact: Dict[str, Any]) -> str:
    kind = artifact.get("kind")
    if isinstance(kind, ArtifactKind):
        return kind.value
    return str(kind or "")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _jsonable_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False)


def _jsonable_repr(value: Any) -> str:
    return repr(_jsonable(value))


_BLACKBOARD_RUNTIME = r'''
@dataclass
class Blackboard:
    values: Dict[str, Any] = field(default_factory=dict)
    schema: Dict[str, Any] = field(default_factory=dict)
    runtime_params: Dict[str, Any] = field(default_factory=dict)

    def write(self, key: str, value: Any) -> None:
        if key:
            self.values[key] = value

    def resolve_ref(self, ref: str) -> Any:
        if ref.startswith("params."):
            current = self.runtime_params
            path = ref.removeprefix("params.").split(".")
        else:
            current = self.values
            path = ref.split(".")
        for segment in path:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
                continue
            if isinstance(current, list) and segment.isdigit():
                current = current[int(segment)]
                continue
            raise KeyError(ref)
        return current


_TEMPLATE_REF = re.compile(r"\{([^{}]+)\}")


def resolve_template(template: str, board: Blackboard) -> str:
    return _TEMPLATE_REF.sub(lambda match: str(board.resolve_ref(match.group(1).strip())), template or "")


def locator_from_payload(scope, payload):
    if not isinstance(payload, dict):
        return scope.locator(str(payload or "body"))
    method = payload.get("method")
    if method == "role" or (method is None and payload.get("role")):
        kwargs = {"name": payload.get("name")} if payload.get("name") else {}
        if "exact" in payload:
            kwargs["exact"] = payload.get("exact")
        return scope.get_by_role(payload.get("role"), **kwargs)
    if method == "text":
        kwargs = {"exact": payload.get("exact")} if "exact" in payload else {}
        return scope.get_by_text(payload.get("value", ""), **kwargs)
    if method == "nested":
        return locator_from_payload(locator_from_payload(scope, payload.get("parent") or {}), payload.get("child") or {})
    return scope.locator(payload.get("value", "body"))
'''.strip()


_MAIN_RUNTIME = r'''


async def main():
    kwargs = {}
    for arg in sys.argv[1:]:
        if arg.startswith("--") and "=" in arg:
            key, value = arg[2:].split("=", 1)
            kwargs[key] = value

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context(no_viewport=True, accept_downloads=True)
    page = await context.new_page()
    page.set_default_timeout(60000)
    page.set_default_navigation_timeout(60000)
    try:
        result = await execute_skill(page, **kwargs)
        if result:
            print("SKILL_DATA:" + _json.dumps(result, ensure_ascii=False, default=str))
        print("SKILL_SUCCESS")
    except Exception as exc:
        print(f"SKILL_ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await context.close()
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
'''.rstrip()
