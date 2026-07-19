"""跨对象语义校验与新领域依赖边界守卫。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CoreTrace, CoreTraceTimeline


def _require_binding(
    trace: "CoreTrace",
    name: str,
    *,
    direction: str,
    kinds: set[str],
) -> object:
    matches = [binding for binding in trace.data_bindings if binding.name == name]
    if len(matches) != 1:
        raise ValueError(f"binding.required:{trace.trace_id}:{name}")
    binding = matches[0]
    if binding.direction != direction or binding.kind not in kinds:
        raise ValueError(f"binding.endpoint_mismatch:{trace.trace_id}:{name}")
    return binding


def _connect(
    connections: dict[str, list[tuple[str, str]]],
    binding_name: str,
    endpoint: str,
    role: str = "consume",
) -> None:
    connections.setdefault(binding_name, []).append((endpoint, role))


def validate_trace(trace: "CoreTrace") -> None:
    """校验单条 CoreTrace 的动作、Binding 与 Effect 语义闭合。"""
    binding_names = [binding.name for binding in trace.data_bindings]
    if len(binding_names) != len(set(binding_names)):
        raise ValueError(f"trace.binding_name_duplicate:{trace.trace_id}")

    connections: dict[str, list[tuple[str, str]]] = {}
    scalar_input_kinds = {"literal", "skill_input", "secret", "variable"}
    action_kind = trace.action.kind

    required_slot: tuple[str, set[str]] | None = None
    if action_kind == "navigate" and trace.action.mode == "url":
        required_slot = ("url", {"literal", "skill_input", "variable"})
    elif action_kind == "fill":
        required_slot = ("value", scalar_input_kinds)
    elif action_kind == "press":
        required_slot = ("keys", scalar_input_kinds)
    elif action_kind == "select":
        required_slot = ("option", scalar_input_kinds)
    elif action_kind == "upload":
        required_slot = ("file", {"data_asset"})

    if required_slot is not None:
        slot_name, slot_kinds = required_slot
        slot = _require_binding(
            trace, slot_name, direction="input", kinds=slot_kinds
        )
        if action_kind in {"navigate", "fill", "press", "select"} and (
            slot.kind == "literal" and slot.value is None
        ):
            raise ValueError(f"binding.literal_null_not_supported:{trace.trace_id}:{slot_name}")
        _connect(connections, slot_name, f"action.{action_kind}")

    if action_kind == "extract":
        _require_binding(trace, "result", direction="output", kinds={"variable"})
        _connect(connections, "result", "action.extract", "produce")

    target = getattr(trace.action, "target", None)
    path_steps = target.path or [] if target is not None else []
    for step in path_steps:
        if step.filter_binding is not None:
            _require_binding(
                trace,
                step.filter_binding,
                direction="input",
                kinds=scalar_input_kinds,
            )
            _connect(connections, step.filter_binding, "target.filter")

    effect_kinds = [effect.kind for effect in trace.effects]
    if len(effect_kinds) != len(set(effect_kinds)):
        raise ValueError(f"effect.kind_duplicate:{trace.trace_id}")
    if len(effect_kinds) > 1 and effect_kinds != ["new_page", "download"]:
        raise ValueError(f"effect.combination_not_allowed:{trace.trace_id}")

    if action_kind == "navigate" and "navigation" in effect_kinds:
        raise ValueError(f"effect.navigation_redundant:{trace.trace_id}")

    for effect in trace.effects:
        if effect.kind == "download":
            _require_binding(
                trace, effect.binding, direction="output", kinds={"data_asset"}
            )
            _connect(connections, effect.binding, "effect.download", "produce")
        if effect.kind == "dialog" and effect.input_binding is not None:
            _require_binding(
                trace,
                effect.input_binding,
                direction="input",
                kinds=scalar_input_kinds,
            )
            _connect(connections, effect.input_binding, "effect.dialog")

    for wait in trace.wait_until or []:
        expected_binding = getattr(wait, "expected_binding", None)
        if expected_binding is not None:
            _require_binding(
                trace,
                expected_binding,
                direction="input",
                kinds=scalar_input_kinds,
            )
            _connect(connections, expected_binding, "wait.expected")

    if action_kind == "agent":
        for binding in trace.data_bindings:
            role = "produce" if binding.direction == "output" else "consume"
            _connect(connections, binding.name, "action.agent", role)

    for binding in trace.data_bindings:
        endpoints = connections.get(binding.name, [])
        if not endpoints:
            raise ValueError(f"binding.orphan:{trace.trace_id}:{binding.name}")
        producer_count = sum(role == "produce" for _, role in endpoints)
        if producer_count > 1:
            raise ValueError(f"binding.endpoint_conflict:{trace.trace_id}:{binding.name}")


def validate_timeline(
    timeline: "CoreTraceTimeline", *, external_asset_refs: set[str] | None = None
) -> None:
    """Fail-closed Timeline validator with stable machine-readable prefixes."""

    external_assets = set(external_asset_refs or set())

    trace_ids = [trace.trace_id for trace in timeline.traces]
    if len(trace_ids) != len(set(trace_ids)):
        raise ValueError("timeline.trace_id_duplicate")

    sequences = [trace.sequence for trace in timeline.traces]
    if len(sequences) != len(set(sequences)):
        raise ValueError("timeline.sequence_duplicate")
    if sequences != sorted(sequences):
        raise ValueError("timeline.sequence_not_ascending")

    known_pages = {"main"}
    closed_pages: set[str] = set()
    produced_variables: set[str] = set()
    produced_assets: set[str] = set()
    for trace in timeline.traces:
        validate_trace(trace)
        if trace.scope.page_ref not in known_pages or trace.scope.page_ref in closed_pages:
            raise ValueError(f"timeline.page_not_introduced:{trace.scope.page_ref}")
        if trace.action.kind == "switch_page" and (
            trace.action.page_ref not in known_pages
            or trace.action.page_ref in closed_pages
        ):
            raise ValueError(f"timeline.page_not_introduced:{trace.action.page_ref}")

        prior_variables = set(produced_variables)
        prior_assets = set(produced_assets) | external_assets
        for binding in trace.data_bindings:
            if binding.kind == "variable":
                if binding.direction == "input" and not any(
                    binding.ref == ref or binding.ref.startswith(ref + ".")
                    for ref in prior_variables
                ):
                    raise ValueError(f"timeline.variable_not_produced:{binding.ref}")
            if (
                binding.kind == "data_asset"
                and binding.direction == "input"
                and binding.ref not in prior_assets
            ):
                raise ValueError(f"timeline.data_asset_not_produced:{binding.ref}")

        for binding in trace.data_bindings:
            if binding.kind == "variable" and binding.direction == "output":
                if any(
                    binding.ref == ref
                    or binding.ref.startswith(ref + ".")
                    or ref.startswith(binding.ref + ".")
                    for ref in produced_variables
                ):
                    raise ValueError(f"timeline.variable_producer_conflict:{binding.ref}")
                produced_variables.add(binding.ref)
            if binding.kind == "data_asset" and binding.direction == "output":
                if binding.ref in produced_assets:
                    raise ValueError(f"timeline.data_asset_producer_duplicate:{binding.ref}")
                produced_assets.add(binding.ref)

        for effect in trace.effects:
            if effect.kind == "new_page":
                if effect.page_ref in known_pages:
                    raise ValueError(f"timeline.page_already_introduced:{effect.page_ref}")
                known_pages.add(effect.page_ref)
        if trace.action.kind == "close_page":
            closed_pages.add(trace.scope.page_ref)


def validate_timeline_payload(
    payload: object, *, external_asset_refs: set[str] | None = None
) -> "CoreTraceTimeline":
    """Parse and validate a Timeline with explicit SkillDefinition asset inputs.

    This is the public Compiler boundary for the two-input validation case. The
    Timeline model remains fail-closed when no external asset references are supplied.
    """

    from .models import CoreTraceTimeline

    return CoreTraceTimeline.model_validate(
        payload,
        context={"external_asset_refs": set(external_asset_refs or set())},
    )


def find_architecture_violations(package_root: Path) -> list[str]:
    """Return deterministic AST import-boundary violations under ``package_root``."""

    violations: list[str] = []
    creation_symbols = {
        "TraceCandidate", "ScopeHint", "TargetHint", "ActionHint", "NavigateHint",
        "ClickHint", "FillHint", "PressHint", "SelectHint", "SetCheckedHint",
        "HoverHint", "UploadHint", "ScrollHint", "ExtractTextHint",
        "ExtractAttributeHint", "ExtractTableHint", "SwitchPageHint", "ClosePageHint",
        "AgentHint", "UnsupportedHint", "BindingHint", "ExecutionError", "ExecutionState",
        "RunningExecution", "SucceededExecution", "FailedExecution", "CancelledExecution",
        "BrowserFact", "RuntimeScope", "NavigationFact", "NewPageFact", "DownloadFact",
        "DialogFact", "PageActivatedFact", "PageClosedFact", "NavigationFactDetail",
        "NewPageFactDetail", "DownloadFactDetail", "DialogFactDetail", "SettlementResult",
        "Diagnostic", "AcceptedSettlement", "RejectedSettlement",
    }
    compiler_allowed_contracts = {
        "CoreTrace", "CoreTraceTimeline", "SkillDefinition", "SkillManifest",
        "validate_trace", "validate_timeline", "validate_timeline_payload",
    }

    for path in sorted(package_root.rglob("*.py")):
        relative_path = path.relative_to(package_root)
        relative = relative_path.as_posix()
        is_compiler = "compiler" in relative_path.parts or relative_path.name == "compiler.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            names: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                names = [alias.name for alias in node.names]
            else:
                continue

            for module in modules:
                legacy_module = (
                    module == "rpa"
                    or module.startswith("rpa.")
                    or module == "backend.rpa"
                    or module.startswith("backend.rpa.")
                )
                if legacy_module:
                    violations.append(
                        f"{relative}:{node.lineno}: forbidden import '{module}'"
                    )
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "backend" and "rpa" in names:
                    violations.append(
                        f"{relative}:{node.lineno}: forbidden import 'backend.rpa'"
                    )
                if node.level and (
                    module == "rpa"
                    or module.startswith("rpa.")
                    or (not module and "rpa" in names)
                ):
                    violations.append(
                        f"{relative}:{node.lineno}: forbidden relative import '{module}'"
                    )
            if not is_compiler:
                continue

            if isinstance(node, ast.Import):
                for module in modules:
                    root = module.split(".", 1)[0]
                    if root not in sys.stdlib_module_names:
                        violations.append(
                            f"{relative}:{node.lineno}: compiler forbidden import '{module}'"
                        )
                continue

            module = node.module or ""
            is_internal_relative = node.level == 1
            is_contract_import = (
                (node.level == 0 and module == "rpa_agent.contracts")
                or (node.level == 2 and module == "contracts")
            )
            if is_contract_import:
                for name in names:
                    if name not in compiler_allowed_contracts:
                        violations.append(
                            f"{relative}:{node.lineno}: compiler forbidden symbol '{name}'"
                        )
                continue
            if is_internal_relative:
                for name in names:
                    if name in creation_symbols:
                        violations.append(
                            f"{relative}:{node.lineno}: compiler forbidden symbol '{name}'"
                        )
                continue

            root = module.split(".", 1)[0]
            if node.level == 0 and (root in sys.stdlib_module_names or module == "__future__"):
                continue
            shown_module = "." * node.level + module
            violations.append(
                f"{relative}:{node.lineno}: compiler forbidden import '{shown_module}'"
            )

    return sorted(violations, key=lambda item: (item.split(":")[0], int(item.split(":")[1])))
