"""CoreTrace v0.1 的显式动作 Renderer。"""

from __future__ import annotations

from typing import Callable

from ..contracts import CoreTrace
from .plan import BrowserCompilePlan


def _binding_expression(binding: object) -> str:
    kind = getattr(binding, "kind")
    if kind == "literal":
        return repr(getattr(binding, "value"))
    ref = getattr(binding, "ref")
    if kind == "skill_input":
        return f"ctx.inputs.require({ref!r})"
    if kind == "secret":
        return f"await ctx.secrets.require({ref!r})"
    if kind == "variable":
        return f"ctx.variables.require({ref!r})"
    if kind == "data_asset":
        return f"ctx.assets.require({ref!r})"
    raise ValueError(f"binding.unsupported:{kind}")


def _binding(trace: CoreTrace, name: str) -> object:
    return next(item for item in trace.data_bindings if item.name == name)


def _render_navigate(trace: CoreTrace) -> list[str]:
    mode = trace.action.mode
    if mode == "url":
        value = _binding_expression(_binding(trace, "url"))
        return [f"await page.goto(str({value}))"]
    return [f"await page.{mode}()"]


def _render_click(trace: CoreTrace) -> list[str]:
    kwargs = []
    if trace.action.button != "left":
        kwargs.append(f"button={trace.action.button!r}")
    if trace.action.count == 2:
        return [f"await target.dblclick({', '.join(kwargs)})" if kwargs else "await target.dblclick()"]
    return [f"await target.click({', '.join(kwargs)})" if kwargs else "await target.click()"]


def _render_fill(trace: CoreTrace) -> list[str]:
    value = _binding_expression(_binding(trace, "value"))
    return [f"await target.fill(str({value}))"]


def _render_press(trace: CoreTrace) -> list[str]:
    keys = _binding_expression(_binding(trace, "keys"))
    return [f"await target.press(str({keys}))"]


def _render_select(trace: CoreTrace) -> list[str]:
    option = _binding_expression(_binding(trace, "option"))
    return [
        f"option = str({option})",
        "await ctx.steps.select_option(target=target, option=option)",
    ]


def _render_set_checked(trace: CoreTrace) -> list[str]:
    return ["await target.check()" if trace.action.checked else "await target.uncheck()"]


def _render_hover(trace: CoreTrace) -> list[str]:
    return ["await target.hover()"]


def _render_upload(trace: CoreTrace) -> list[str]:
    asset = _binding_expression(_binding(trace, "file"))
    return [f"await target.set_input_files({asset})"]


def _render_scroll(trace: CoreTrace) -> list[str]:
    spec = {
        "direction": trace.action.direction,
        "amount": trace.action.amount,
        "unit": trace.action.unit,
    }
    if trace.action.target is not None:
        script = """(element, spec) => {
  const horizontal = spec.direction === 'left' || spec.direction === 'right';
  const sign = spec.direction === 'up' || spec.direction === 'left' ? -1 : 1;
  const base = spec.unit === 'viewport'
    ? (horizontal ? element.clientWidth : element.clientHeight)
    : 1;
  element.scrollBy(horizontal ? sign * spec.amount * base : 0,
                   horizontal ? 0 : sign * spec.amount * base);
}"""
        return [f"await target.evaluate({script!r}, {spec!r})"]
    script = """(spec) => {
  const horizontal = spec.direction === 'left' || spec.direction === 'right';
  const sign = spec.direction === 'up' || spec.direction === 'left' ? -1 : 1;
  const base = spec.unit === 'viewport'
    ? (horizontal ? window.innerWidth : window.innerHeight)
    : 1;
  window.scrollBy(horizontal ? sign * spec.amount * base : 0,
                  horizontal ? 0 : sign * spec.amount * base);
}"""
    return [f"await page.evaluate({script!r}, {spec!r})"]


def _render_extract(trace: CoreTrace) -> list[str]:
    if trace.action.mode == "text":
        expression = "await target.inner_text()"
    elif trace.action.mode == "attribute":
        expression = f"await target.get_attribute({trace.action.attribute!r})"
    else:
        columns = [column.model_dump(mode="python", exclude_none=True) for column in trace.action.columns]
        expression = f"await ctx.steps.extract_table(target=target, columns={columns!r})"
    return [f"action_output = {expression}"]


def _render_switch_page(trace: CoreTrace) -> list[str]:
    return [f"ctx.pages.activate({trace.action.page_ref!r})"]


def _render_close_page(trace: CoreTrace) -> list[str]:
    return [f"await ctx.pages.close({trace.scope.page_ref!r})"]


def _render_agent(trace: CoreTrace, plan: BrowserCompilePlan) -> list[str]:
    policy = plan.agent_policies.get(trace.trace_id)
    inputs = {
        binding.name: _binding_expression(binding)
        for binding in trace.data_bindings
        if binding.direction == "input" and binding.kind not in {"secret", "data_asset"}
    }
    secrets = {
        binding.name: _binding_expression(binding)
        for binding in trace.data_bindings
        if binding.direction == "input" and binding.kind == "secret"
    }
    assets = {
        binding.name: _binding_expression(binding)
        for binding in trace.data_bindings
        if binding.direction == "input" and binding.kind == "data_asset"
    }
    input_source = "{" + ", ".join(f"{name!r}: {expression}" for name, expression in inputs.items()) + "}"
    secret_source = "{" + ", ".join(f"{name!r}: {expression}" for name, expression in secrets.items()) + "}"
    asset_source = "{" + ", ".join(f"{name!r}: {expression}" for name, expression in assets.items()) + "}"
    outputs = [binding for binding in trace.data_bindings if binding.direction == "output"]
    output_names = tuple(binding.name for binding in outputs)
    asset_output_refs = {
        binding.name: binding.ref for binding in outputs if binding.kind == "data_asset"
    }
    required_paths = plan.agent_required_paths.get(trace.trace_id, {})
    scope_hint = {
        "page_ref": trace.scope.page_ref,
        "frame_path": [frame.model_dump(mode="python") for frame in trace.scope.frame_path],
    }
    lines = [
        "agent_outputs = await ctx.agent.execute(",
        "    scope=scope,",
        "    target=target," if trace.action.target is not None else "    target=None,",
        f"    instruction={trace.action.instruction!r},",
        f"    inputs={input_source},",
        "    variables=ctx.variables.snapshot(),",
        f"    sensitive_data={secret_source},",
        f"    data_assets={asset_source},",
        f"    output_names={output_names!r},",
        f"    asset_output_refs={asset_output_refs!r},",
        f"    required_paths={required_paths!r},",
        f"    step_id={trace.trace_id!r},",
        f"    scope_hint={scope_hint!r},",
        f"    expected_effects={tuple(effect.model_dump(mode='python', exclude_none=True) for effect in policy.expected_effects) if policy else ()!r},",
        f"    model_policy={policy.model_policy.model_dump(mode='python') if policy else {'mode': 'runtime_default', 'model_ref': None}!r},",
        ")",
    ]
    return lines


_SIMPLE_RENDERERS: dict[str, Callable[[CoreTrace], list[str]]] = {
    "navigate": _render_navigate,
    "click": _render_click,
    "fill": _render_fill,
    "press": _render_press,
    "select": _render_select,
    "set_checked": _render_set_checked,
    "hover": _render_hover,
    "upload": _render_upload,
    "scroll": _render_scroll,
    "extract": _render_extract,
    "switch_page": _render_switch_page,
    "close_page": _render_close_page,
}

RENDERER_KINDS = frozenset((*_SIMPLE_RENDERERS, "agent"))


def render_action(trace: CoreTrace, plan: BrowserCompilePlan) -> list[str]:
    if trace.action.kind == "agent":
        return _render_agent(trace, plan)
    return _SIMPLE_RENDERERS[trace.action.kind](trace)


def render_outputs(trace: CoreTrace) -> list[str]:
    if trace.action.kind == "extract":
        binding = _binding(trace, "result")
        return [f"ctx.variables.write({binding.ref!r}, action_output)"]
    if trace.action.kind != "agent":
        return []
    lines: list[str] = []
    for binding in trace.data_bindings:
        if binding.direction != "output":
            continue
        if binding.kind == "variable":
            lines.append(f"ctx.variables.write({binding.ref!r}, agent_outputs[{binding.name!r}])")
        elif binding.kind == "data_asset":
            lines.append(f"ctx.assets.register({binding.ref!r}, agent_outputs[{binding.name!r}])")
    return lines


def binding_expression(binding: object) -> str:
    """仅供代码组装器解析 Target/Effect/Wait 的显式 Binding。"""

    return _binding_expression(binding)
