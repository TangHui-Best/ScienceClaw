"""Browser-use host helpers that preserve explicit business bindings.

The host may resolve a variable to a transient tool argument, but the recorded
action always carries the caller-provided variable reference.  No value based
binding inference is permitted here.
"""

from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import json
import os
import secrets
from types import SimpleNamespace
from typing import Awaitable, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

from pydantic import JsonValue, create_model
from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema

from browser_use import (
    Agent,
    BrowserSession as BrowserUseSession,
    ChatAnthropic,
    ChatOpenAI,
)
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

from ..api import AgentInstructionRequest
from ..browser_use import NonSopActionClassification, RecordingRoundReport
from ..contracts import CoreTrace
from ..runtime.variables import DataAssetHandle


MAX_VARIABLE_BYTES = 16 * 1024
MAX_VARIABLE_COUNT = 200
MAX_VARIABLE_TOTAL_BYTES = 128 * 1024
MAX_ASSET_SUMMARY_BYTES = 4 * 1024
MAX_ASSET_COUNT = 20
MAX_ASSET_TOTAL_BYTES = 64 * 1024
MAX_PAGE_ALIASES = 20
MAX_AGENT_CONTEXT_BYTES = 256 * 1024
MAX_AGENT_CONTEXT_TOKENS = 32 * 1024


class _TextFallbackChatAnthropic(ChatAnthropic):
    """Accept Anthropic-compatible gateways that return JSON as text.

    Some compatible gateways ignore a forced ``tool_choice`` and put the
    structured Browser-use payload in a text block.  Browser-use already has
    a strict schema-validation fallback for that response shape, but only
    enables it for auto tool choice.  Selecting auto here keeps native tool
    calls preferred while making the existing validated text fallback
    reachable; malformed prose still fails closed.
    """

    async def ainvoke(self, messages, output_format=None, **kwargs):
        if output_format is not None:
            # Compatible gateways can intermittently ignore either forced or
            # auto tool choice. Alternate the protocol across Browser-use's
            # bounded retries, while keeping each individual response under
            # the same strict output schema.
            self._use_auto_tool_choice = not getattr(
                self, "_use_auto_tool_choice", False
            )
        try:
            return await super().ainvoke(
                messages, output_format=output_format, **kwargs
            )
        except ModelProviderError as exc:
            if (
                output_format is None
                or "Expected tool use in response but none found" not in str(exc)
            ):
                raise

            # A few Anthropic-compatible gateways discard ``tool_choice`` even
            # when they otherwise serve the requested model correctly. Make one
            # explicit text-JSON request before handing control back to
            # Browser-use's bounded retry loop. The result is still accepted
            # only after exact Pydantic validation against the same schema.
            schema = SchemaOptimizer.create_optimized_json_schema(output_format)
            fallback_messages = [
                *messages,
                UserMessage(
                    content=(
                        "The compatibility gateway omitted the requested tool_use. "
                        "Return only one JSON object (plain or fenced), with no prose, "
                        "that validates against this exact JSON Schema: "
                        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
                    )
                ),
            ]
            text_result = await ChatAnthropic.ainvoke(
                self, fallback_messages, output_format=None, **kwargs
            )
            parsed = output_format.model_validate_json(
                _validated_json_text(text_result.completion)
            )
            return ChatInvokeCompletion(
                completion=parsed,
                usage=text_result.usage,
                stop_reason=text_result.stop_reason,
                thinking=text_result.thinking,
                redacted_thinking=text_result.redacted_thinking,
                stop_details=text_result.stop_details,
            )

    def _requires_auto_tool_choice(self) -> bool:
        return getattr(self, "_use_auto_tool_choice", True)


def _validated_json_text(value: str) -> str:
    """Extract one fenced or plain JSON object without accepting prose."""

    text = value.strip()
    if text.startswith("```"):
        first_line_end = text.find("\n")
        if first_line_end < 0 or not text.endswith("```"):
            raise ValueError("browser_use_host.structured_output_invalid")
        text = text[first_line_end + 1 : -3].strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise ValueError("browser_use_host.structured_output_invalid")
    return text


class _TextJSONChatOpenAI(ChatOpenAI):
    """Validate JSON fenced by OpenAI-compatible Anthropic gateways."""

    async def ainvoke(self, messages, output_format=None, **kwargs):
        if output_format is None:
            return await super().ainvoke(messages, output_format=None, **kwargs)
        openai_messages = OpenAIMessageSerializer.serialize_messages(messages)
        response_format = {
            "name": "agent_output",
            "strict": True,
            "schema": SchemaOptimizer.create_optimized_json_schema(
                output_format,
                remove_min_items=self.remove_min_items_from_schema,
                remove_defaults=self.remove_defaults_from_schema,
            ),
        }
        model_params: dict[str, object] = {}
        if self.temperature is not None:
            model_params["temperature"] = self.temperature
        if self.frequency_penalty is not None:
            model_params["frequency_penalty"] = self.frequency_penalty
        if self.max_completion_tokens is not None:
            model_params["max_completion_tokens"] = self.max_completion_tokens
        if self.top_p is not None:
            model_params["top_p"] = self.top_p
        if self.seed is not None:
            model_params["seed"] = self.seed
        try:
            response = await self.get_client().chat.completions.create(
                model=self.model,
                messages=openai_messages,
                response_format=ResponseFormatJSONSchema(
                    json_schema=response_format, type="json_schema"
                ),
                **model_params,
            )
            choice = response.choices[0] if response.choices else None
            if choice is None or choice.message.content is None:
                raise ValueError("browser_use_host.structured_output_missing")
            parsed = output_format.model_validate_json(
                _validated_json_text(choice.message.content)
            )
            return ChatInvokeCompletion(
                completion=parsed,
                usage=self._get_usage(response),
                stop_reason=choice.finish_reason,
            )
        except Exception as exc:
            raise ModelProviderError(message=str(exc), model=self.name) from exc


def _canonical_size(value: object) -> int:
    return len(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    )


def _validate_agent_context(payload: Mapping[str, object]) -> None:
    variables = payload.get("variables", {})
    if not isinstance(variables, Mapping):
        raise ValueError("agent_context.variables_invalid")
    if len(variables) > MAX_VARIABLE_COUNT:
        raise ValueError("agent_context_variables_too_large")
    variable_sizes = [_canonical_size(value) for value in variables.values()]
    if any(size > MAX_VARIABLE_BYTES for size in variable_sizes):
        raise ValueError("agent_context_variable_oversize")
    if sum(variable_sizes) > MAX_VARIABLE_TOTAL_BYTES:
        raise ValueError("agent_context_variables_too_large")
    assets = payload.get("data_assets", {})
    if not isinstance(assets, Mapping) or len(assets) > MAX_ASSET_COUNT:
        raise ValueError("agent_context_assets_too_large")
    asset_sizes = [_canonical_size(value) for value in assets.values()]
    if any(size > MAX_ASSET_SUMMARY_BYTES for size in asset_sizes) or sum(asset_sizes) > MAX_ASSET_TOTAL_BYTES:
        raise ValueError("agent_context_assets_too_large")
    aliases = payload.get("page_aliases", payload.get("scope_hint", {}))
    if isinstance(aliases, Mapping) and len(aliases) > MAX_PAGE_ALIASES:
        raise ValueError("agent_context_page_aliases_too_large")
    total = _canonical_size(payload)
    if total > MAX_AGENT_CONTEXT_BYTES or (total + 3) // 4 > MAX_AGENT_CONTEXT_TOKENS:
        raise ValueError("agent_context_too_large")



def _safe_current_page(page: object) -> Mapping[str, object] | None:
    raw_url = str(getattr(page, "url", ""))
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return {"url": safe_url, "title": "current browser page"}


def semantic_hints_from_browser_use_node(
    node: object,
) -> tuple[tuple[Mapping[str, object], ...], Mapping[str, object]]:
    """Project stable semantic hints; Browser-use indexes/ids are discarded."""

    target_locators = _semantic_locators(node)
    if not target_locators:
        raise ValueError("browser_use_host.target_locator_unavailable")
    ancestors: list[object] = []
    current = getattr(node, "parent_node", None)
    while current is not None:
        if str(getattr(current, "tag_name", "")).lower() == "iframe":
            ancestors.append(current)
        current = getattr(current, "parent_node", None)
    frame_steps: list[Mapping[str, object]] = []
    for iframe in reversed(ancestors):
        locators = _semantic_locators(iframe)
        if not locators:
            raise ValueError("browser_use_host.frame_locator_unavailable")
        frame_steps.append(
            {
                "name": _semantic_name(iframe),
                "locators": list(locators),
            }
        )
    return tuple(frame_steps), {
        "name": _semantic_name(node),
        "locators": list(target_locators),
    }


def _semantic_name(node: object) -> str:
    ax = getattr(node, "ax_node", None)
    name = getattr(ax, "name", None)
    if isinstance(name, str) and name.strip():
        return " ".join(name.split())[:256]
    attributes = getattr(node, "attributes", {})
    if isinstance(attributes, Mapping):
        for key in ("aria-label", "placeholder", "title", "name", "data-testid"):
            value = attributes.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())[:256]
    tag = str(getattr(node, "tag_name", "")).strip().lower()
    if tag:
        return tag
    raise ValueError("browser_use_host.target_name_unavailable")


def _semantic_locators(node: object) -> tuple[Mapping[str, object], ...]:
    attrs = getattr(node, "attributes", {})
    if not isinstance(attrs, Mapping):
        attrs = {}
    locators: list[Mapping[str, object]] = []
    test_id = attrs.get("data-testid")
    if isinstance(test_id, str) and test_id.strip():
        locators.append(
            {"strategy": "test_id", "value": test_id.strip(), "exact": True}
        )
    role = attrs.get("role")
    if not isinstance(role, str) or not role.strip():
        role = {
            "button": "button",
            "a": "link",
            "textarea": "textbox",
            "select": "combobox",
            "input": "textbox",
        }.get(str(getattr(node, "tag_name", "")).lower())
    if isinstance(role, str) and role.strip():
        locator: dict[str, object] = {
            "strategy": "role",
            "role": role.strip(),
            "exact": True,
        }
        ax_name = getattr(getattr(node, "ax_node", None), "name", None)
        if isinstance(ax_name, str) and ax_name.strip():
            locator["name"] = " ".join(ax_name.split())
        locators.append(locator)
    for attribute, strategy in (
        ("placeholder", "placeholder"),
        ("title", "title"),
        ("alt", "alt_text"),
    ):
        value = attrs.get(attribute)
        if isinstance(value, str) and value.strip():
            locators.append(
                {"strategy": strategy, "value": value.strip(), "exact": True}
            )
    return tuple(locators)


def _execution_guidance(instruction: str) -> str | None:
    instruction_lower = instruction.casefold()
    if "最相关" in instruction or "most related" in instruction_lower:
        return (
            "Inspect repositories visible on the current page, choose exactly one "
            "strongest semantic match, click its repository link, and finish only "
            "after the repository root page is open. Do not use global site search."
        )
    if "star" in instruction_lower or "星标" in instruction:
        return (
            "Stay on the current repository page, read the exact repository star "
            "counter, and return that numeric count. Do not navigate elsewhere."
        )
    return None


def build_agent_task(
    hosted: object,
    request: AgentInstructionRequest,
    *,
    page: object | None = None,
) -> str:
    creation = getattr(getattr(hosted, "browser"), "creation")
    # An AI instruction sees the complete non-secret session variable snapshot.
    # required_variable_refs is only a backwards-compatible context hint and must
    # never hide variables produced by earlier timeline items.
    variables = creation.variables.snapshot()
    port = getattr(getattr(hosted, "browser"), "port")
    page = page if page is not None else getattr(port, "main_page")
    payload = {
        "current_instruction": request.instruction,
        "business_terms": list(request.business_terms),
        "variables": variables,
        "allowed_inputs": dict(request.allowed_inputs),
        "allowed_secret_names": list(request.allowed_secret_names),
        "allowed_data_assets": dict(request.allowed_data_assets),
        "page_aliases": dict(request.page_aliases),
    }
    page_state = _safe_current_page(page)
    if page_state is not None:
        payload["current_page_state"] = page_state
    guidance = _execution_guidance(request.instruction)
    if guidance is not None:
        payload["execution_guidance"] = guidance
    _validate_agent_context(payload)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)


async def _model_for(owner_id: str, model_ref: str | None = None) -> object:
    from backend.models import get_model_config, resolve_default_model_config

    if model_ref:
        selected = await get_model_config(model_ref)
        if selected is None or not selected.is_active or (
            not selected.is_system and selected.user_id != owner_id
        ):
            raise RuntimeError("browser_use_host.model_unavailable")
        config: Mapping[str, object] | None = selected.model_dump(mode="python")
    else:
        config = await resolve_default_model_config(owner_id)
    if not isinstance(config, Mapping):
        raise RuntimeError("browser_use_host.model_unavailable")
    model = config.get("model_name")
    api_key = config.get("api_key")
    if not isinstance(model, str) or not model or not isinstance(api_key, str) or not api_key:
        raise RuntimeError("browser_use_host.model_invalid")
    base_url = config.get("base_url")
    provider = str(config.get("provider") or "openai").strip().lower()
    common = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url if isinstance(base_url, str) and base_url else None,
    }
    if provider == "anthropic":
        return _TextFallbackChatAnthropic(**common)
    return _TextJSONChatOpenAI(
        **common,
    )


async def _resolve_model(
    factory: Callable[..., Awaitable[object]], owner_id: str, model_ref: str | None
) -> object:
    if model_ref is None:
        return await factory(owner_id)
    try:
        return await factory(owner_id, model_ref)
    except TypeError:
        # Test doubles and older host adapters may expose the legacy one-argument shape.
        return await factory(owner_id)


async def execute_browser_use_instruction(
    hosted: object,
    request: AgentInstructionRequest,
    *,
    model_factory: Callable[[str], Awaitable[object]] = _model_for,
    agent_factory: Callable[..., object] = Agent,
    browser_session_factory: Callable[..., object] = BrowserUseSession,
) -> RecordingRoundReport:
    port = getattr(getattr(hosted, "browser"), "port")
    cdp_url = getattr(port, "browser_use_cdp_url", None)
    if not isinstance(cdp_url, str) or not cdp_url:
        raise RuntimeError("browser_use_host.cdp_url_unavailable")
    model = await _resolve_model(
        model_factory,
        str(getattr(hosted, "owner_id")),
        request.model_id,
    )
    browser_session = browser_session_factory(cdp_url=cdp_url, keep_alive=True)
    await browser_session.start()
    try:
        page = await port.active_page_object()
        await _focus_exact_page(browser_session, page)
        output_types = {
            "string": str,
            "number": int | float,
            "boolean": bool,
            "json": JsonValue,
        }
        output_fields = {
            output.name: (output_types[output.value_type], ...)
            for output in request.declared_outputs
        }
        output_model = (
            create_model("RecordingAgentOutputs", **output_fields)
            if output_fields
            else None
        )
        agent = agent_factory(
            task=build_agent_task(hosted, request, page=page),
            llm=model,
            browser_session=browser_session,
            output_model_schema=output_model,
            use_vision=False,
            enable_signal_handler=False,
        )
        observed_history_items = 0

        async def observe_completed_step(native_agent: object) -> None:
            # Deliberately read-only: inspect native history after execution,
            # append child evidence, and never return a planner/control signal.
            nonlocal observed_history_items
            history_list = getattr(native_agent, "history", None)
            history_items = tuple(getattr(history_list, "history", ()) or ())
            for history_item in history_items[observed_history_items:]:
                await _attach_native_history_item(
                    hosted,
                    step_id=str(getattr(hosted, "active_operation_id")),
                    history_item=history_item,
                )
            observed_history_items = len(history_items)

        history = await agent.run(on_step_end=observe_completed_step)
        if history.is_done() is not True or history.is_successful() is not True:
            raise RuntimeError("browser_use_host.instruction_failed")
        if output_model is not None:
            structured = history.get_structured_output(output_model)
            if structured is None:
                raise RuntimeError("browser_use_host.output_missing")
            values = structured.model_dump(mode="python")
            step_id = str(getattr(hosted, "active_operation_id"))
            getattr(getattr(hosted, "browser"), "creation").variables.write_many(
                {
                    output.variable_ref: values[output.name]
                    for output in request.declared_outputs
                },
                producer_candidate_id=step_id,
            )
        action_names = tuple(history.action_names())
        non_sop = tuple(
            NonSopActionClassification(
                action_name=name, status="succeeded", reason="control_action"
            )
            for name in action_names
            if name == "done"
        )
        actual_action_count = sum(name != "done" for name in action_names)
        return RecordingRoundReport(
            invocation_count=len(action_names),
            actual_action_count=actual_action_count,
            candidate_ids=(),
            non_sop=non_sop,
        )
    finally:
        await browser_session.stop()


async def _attach_native_history_item(
    hosted: object, *, step_id: str, history_item: object
) -> None:
    model_output = getattr(history_item, "model_output", None)
    if model_output is None:
        return
    actions = tuple(getattr(model_output, "action", ()) or ())
    results = tuple(getattr(history_item, "result", ()) or ())
    state = getattr(history_item, "state", None)
    elements = tuple(getattr(state, "interacted_element", ()) or ())
    port = getattr(getattr(hosted, "browser"), "port")
    page = await port.active_page_object()
    runtime_page_ref = port.page_runtime_ref(page)
    page_ref = getattr(getattr(hosted, "browser"), "creation").pages.resolve(
        runtime_page_ref
    )
    for index, action_model in enumerate(actions):
        result = results[index] if index < len(results) else None
        if result is not None and getattr(result, "error", None):
            continue
        payload = action_model.model_dump(mode="python", exclude_none=True)
        if not isinstance(payload, Mapping) or len(payload) != 1:
            continue
        action_name, params = next(iter(payload.items()))
        if not isinstance(params, Mapping):
            continue
        action: dict[str, object]
        bindings: list[dict[str, object]] = []
        frame_path: tuple[Mapping[str, object], ...] = ()
        if action_name == "navigate":
            url = params.get("url")
            if not isinstance(url, str) or not url:
                continue
            action = {"kind": "navigate", "mode": "url"}
            bindings.append(
                {
                    "name": "url",
                    "direction": "input",
                    "kind": "literal",
                    "value": url,
                    "sensitive": False,
                }
            )
        elif action_name == "click":
            element = elements[index] if index < len(elements) else None
            if element is None:
                continue
            try:
                frame_path, target = semantic_hints_from_browser_use_node(element)
            except ValueError:
                continue
            action = {"kind": "click", "target": target}
        else:
            continue
        trace = CoreTrace.model_validate(
            {
                "trace_id": "trace_obs_" + secrets.token_hex(12),
                "sequence": 1,
                "scope": {"page_ref": page_ref, "frame_path": list(frame_path)},
                "action": action,
                "data_bindings": bindings,
                "effects": [],
            }
        )
        getattr(getattr(hosted, "browser"), "creation").attach_ai_observation(
            step_id=step_id, trace=trace
        )


def build_runtime_agent_backend(
    hosted: object,
    *,
    model_factory: Callable[[str], Awaitable[object]] = _model_for,
    agent_factory: Callable[..., object] = Agent,
    browser_session_factory: Callable[..., object] = BrowserUseSession,
):
    async def backend(
        *,
        scope: object,
        target: object | None,
        instruction: str,
        inputs: Mapping[str, object],
        output_names: tuple[str, ...],
        asset_output_refs: Mapping[str, str] | None = None,
        required_paths: Mapping[str, tuple[str, ...]],
        variables: Mapping[str, object] | None = None,
        sensitive_data: Mapping[str, object] | None = None,
        data_assets: Mapping[str, object] | None = None,
        step_id: str = "legacy_agent_step",
        scope_hint: Mapping[str, object] | None = None,
        expected_effects: tuple[Mapping[str, object], ...] = (),
        model_policy: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        del target
        variables = variables or {}
        sensitive_data = sensitive_data or {}
        data_assets = data_assets or {}
        scope_hint = scope_hint or {}
        model_policy = model_policy or {"mode": "runtime_default", "model_ref": None}
        asset_output_refs = asset_output_refs or {}
        page = getattr(scope, "page", None)
        if callable(page):
            page = page()
        if page is None and hasattr(scope, "bring_to_front"):
            page = scope
        bring_to_front = getattr(page, "bring_to_front", None)
        if callable(bring_to_front):
            await bring_to_front()
        port = getattr(getattr(hosted, "browser"), "port")
        cdp_url = getattr(port, "browser_use_cdp_url", None)
        if not isinstance(cdp_url, str) or not cdp_url:
            raise RuntimeError("browser_use_host.cdp_url_unavailable")
        model_ref = (
            str(model_policy.get("model_ref"))
            if model_policy.get("mode") == "configured_model"
            and model_policy.get("model_ref")
            else None
        )
        model = await _resolve_model(
            model_factory, str(getattr(hosted, "owner_id")), model_ref
        )
        scalar_output_names = tuple(
            name for name in output_names if name not in asset_output_refs
        )
        fields = {name: (JsonValue, ...) for name in scalar_output_names}
        output_model = create_model("RuntimeAgentOutputs", **fields) if fields else None
        task_payload = {
                "instruction": instruction,
                "step_id": step_id,
                "scope_hint": dict(scope_hint),
                "inputs": dict(inputs),
                "variables": dict(variables),
                "allowed_secret_names": sorted(sensitive_data),
                "data_assets": {
                    name: (
                        value.public_contract()
                        if callable(getattr(value, "public_contract", None))
                        else {"ref": name}
                    )
                    for name, value in data_assets.items()
                },
                "required_outputs": list(scalar_output_names),
                "download_outputs": dict(asset_output_refs),
                "required_paths": {
                    name: list(paths) for name, paths in required_paths.items()
                },
            }
        guidance = _execution_guidance(instruction)
        if guidance is not None:
            task_payload["execution_guidance"] = guidance
        _validate_agent_context(task_payload)
        task = json.dumps(
            task_payload,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        session = browser_session_factory(cdp_url=cdp_url, keep_alive=True)
        available_file_paths: list[str] = []
        for value in data_assets.values():
            try:
                available_file_paths.append(os.fspath(value))
            except TypeError as exc:
                raise RuntimeError("runtime_agent.asset_path_invalid") from exc
        await session.start()
        try:
            if page is None:
                raise RuntimeError("runtime_agent.page_unavailable")
            await _focus_exact_page(session, page)
            agent = agent_factory(
                task=task,
                llm=model,
                browser_session=session,
                output_model_schema=output_model,
                use_vision=False,
                sensitive_data={name: str(value) for name, value in sensitive_data.items()},
                available_file_paths=available_file_paths,
                enable_signal_handler=False,
            )
            history = await agent.run()
            if history.is_done() is not True or history.is_successful() is not True:
                raise RuntimeError("runtime_agent.instruction_failed")
            attachments = _history_attachments(history)
            await _assert_runtime_expected_effects(
                page, expected_effects, attachment_count=len(attachments)
            )
            result: dict[str, object] = {}
            if output_model is not None:
                structured = history.get_structured_output(output_model)
                if structured is None:
                    raise RuntimeError("runtime_agent.output_missing")
                result.update(structured.model_dump(mode="python"))
            if len(attachments) < len(asset_output_refs):
                raise RuntimeError("runtime_agent.download_output_missing")
            for (name, ref), path in zip(sorted(asset_output_refs.items()), attachments):
                result[name] = DataAssetHandle(
                    ref=ref,
                    runtime_value=path,
                    metadata={"name": os.path.basename(path)},
                )
            return result
        finally:
            await session.stop()

    return backend


async def _assert_runtime_expected_effects(
    page: object,
    expected_effects: tuple[Mapping[str, object], ...],
    *,
    attachment_count: int,
) -> None:
    for effect in expected_effects:
        kind = effect.get("kind")
        if kind == "navigation":
            pattern = effect.get("url_pattern")
            if pattern and not fnmatch.fnmatch(str(getattr(page, "url", "")), str(pattern)):
                raise RuntimeError("runtime_agent.expected_navigation_missing")
            continue
        if kind == "download" and attachment_count > 0:
            continue
        # These effects require the runtime EffectCoordinator event ledger. Fail closed
        # until the concrete event has been registered; never infer success from done text.
        raise RuntimeError(f"runtime_agent.expected_effect_unverified:{kind}")


def _history_attachments(history: object) -> list[str]:
    action_results = getattr(history, "action_results", None)
    raw_results = action_results() if callable(action_results) else ()
    attachments: list[str] = []
    for result in raw_results or ():
        for path in getattr(result, "attachments", None) or ():
            if isinstance(path, str) and path and path not in attachments:
                attachments.append(path)
    return attachments


async def _focus_exact_page(browser_session: object, page: object) -> None:
    context = getattr(page, "context", None)
    create_cdp = getattr(context, "new_cdp_session", None)
    focus = getattr(browser_session, "get_or_create_cdp_session", None)
    if not callable(create_cdp) or not callable(focus):
        raise RuntimeError("browser_use_host.exact_page_focus_unavailable")
    playwright_cdp = await create_cdp(page)
    try:
        response = await playwright_cdp.send("Target.getTargetInfo")
    finally:
        detach = getattr(playwright_cdp, "detach", None)
        if callable(detach):
            await detach()
    info = response.get("targetInfo") if isinstance(response, Mapping) else None
    target_id = info.get("targetId") if isinstance(info, Mapping) else None
    if not isinstance(target_id, str) or not target_id:
        raise RuntimeError("browser_use_host.target_id_unavailable")
    await focus(target_id=target_id, focus=True)


async def _playwright_target_id(page: object) -> str:
    context = getattr(page, "context", None)
    create_cdp = getattr(context, "new_cdp_session", None)
    if not callable(create_cdp):
        raise RuntimeError("browser_use_host.target_id_unavailable")
    cdp = await create_cdp(page)
    try:
        response = await cdp.send("Target.getTargetInfo")
    finally:
        detach = getattr(cdp, "detach", None)
        if callable(detach):
            await detach()
    info = response.get("targetInfo") if isinstance(response, Mapping) else None
    target_id = info.get("targetId") if isinstance(info, Mapping) else None
    if not isinstance(target_id, str) or not target_id:
        raise RuntimeError("browser_use_host.target_id_unavailable")
    return target_id


async def _tab_runtime_refs(port: object) -> dict[str, str]:
    result: dict[str, str] = {}
    pages = tuple(getattr(getattr(port, "context"), "pages", ()) or ())
    for page in pages:
        target_id = await _playwright_target_id(page)
        tab_id = target_id[-4:]
        if len(tab_id) != 4 or tab_id in result:
            raise RuntimeError("browser_use_host.target_id_conflict")
        result[tab_id] = port.page_runtime_ref(page)
    return result


async def run_compiled_skill_with_agent(hosted: object, request: object):
    from .default_services import run_compiled_skill

    return await run_compiled_skill(
        hosted,
        request,
        agent_backend=build_runtime_agent_backend(hosted),
    )


__all__ = [
    "build_agent_task",
    "build_runtime_agent_backend",
    "execute_browser_use_instruction",
    "run_compiled_skill_with_agent",
    "semantic_hints_from_browser_use_node",
]
