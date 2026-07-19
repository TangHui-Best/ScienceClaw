"""Browser-use host helpers that preserve explicit business bindings.

The host may resolve a variable to a transient tool argument, but the recorded
action always carries the caller-provided variable reference.  No value based
binding inference is permitted here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
import secrets
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError, create_model

from browser_use import Agent, BrowserSession as BrowserUseSession, ChatOpenAI, Tools
from browser_use.agent.views import ActionResult

from ..api import AgentInstructionRequest
from ..browser_use import (
    BrowserUseInvocationNormalizer,
    BrowserUseRecordingAdapter,
    NonSopActionClassification,
    RecordingRoundReport,
    TargetResolution,
)

from ..contracts.models import BusinessVariableRef, Identifier
from ..creation.session import SessionVariableStore


_VARIABLE_REF = TypeAdapter(BusinessVariableRef)
_INPUT_REF = TypeAdapter(Identifier)


@dataclass(frozen=True, slots=True)
class NormalizedVariableAction:
    action_name: str
    params: Mapping[str, object]
    binding_hints: tuple[Mapping[str, object], ...]
    variable_outputs: Mapping[str, object]
    preflight_error: str | None = None


def normalize_variable_action(
    action_name: str,
    params: Mapping[str, object],
    *,
    variables: SessionVariableStore,
    allowed_inputs: Mapping[str, object] | None = None,
    _allow_input_errors: bool = False,
) -> NormalizedVariableAction:
    """Normalize only the controlled variable-aware Browser-use actions."""

    variable_ref = _validated_variable_ref(params.get("variable_ref"))
    if action_name == "input_variable":
        index = params.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("browser_use_host.index_invalid")
        try:
            value = variables.read(variable_ref)
        except KeyError as exc:
            raise ValueError("browser_use_host.variable_missing") from exc
        if not isinstance(value, (str, int, float, bool)) or value is None:
            raise ValueError("browser_use_host.input_value_not_scalar")
        return NormalizedVariableAction(
            action_name="input",
            params={"index": index, "text": str(value), "clear": True},
            binding_hints=(_binding("value", "input", variable_ref),),
            variable_outputs={},
        )
    if action_name == "select_dropdown_variable":
        index = params.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("browser_use_host.index_invalid")
        try:
            value = variables.read(variable_ref)
        except KeyError as exc:
            raise ValueError("browser_use_host.variable_missing") from exc
        if not isinstance(value, (str, int, float, bool)) or value is None:
            raise ValueError("browser_use_host.input_value_not_scalar")
        return NormalizedVariableAction(
            action_name="select_dropdown",
            params={"index": index, "text": str(value)},
            binding_hints=(_binding("option", "input", variable_ref),),
            variable_outputs={},
        )
    if action_name == "click_variable":
        index = params.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("browser_use_host.index_invalid")
        try:
            variables.read(variable_ref)
        except KeyError as exc:
            raise ValueError("browser_use_host.variable_missing") from exc
        return NormalizedVariableAction(
            action_name="click",
            params={"index": index},
            binding_hints=(_binding("row_key", "input", variable_ref),),
            variable_outputs={},
        )
    if action_name == "extract_variable":
        value = _copy_json(params.get("value"))
        input_bindings, input_error = _extract_input_bindings(
            params.get("input_refs", []),
            allowed_inputs=allowed_inputs or {},
        )
        if input_error is not None and not _allow_input_errors:
            raise ValueError(input_error)
        return NormalizedVariableAction(
            action_name="extract_variable",
            params={"variable_ref": variable_ref, "value": value},
            binding_hints=tuple(
                (*input_bindings, _binding("result", "output", variable_ref))
            ),
            variable_outputs={variable_ref: value},
            preflight_error=input_error,
        )
    raise ValueError("browser_use_host.variable_action_unsupported")


def normalize_allowed_input_action(
    action_name: str,
    params: Mapping[str, object],
    *,
    allowed_inputs: Mapping[str, object],
    _allow_unknown: bool = False,
) -> NormalizedVariableAction:
    if action_name != "click_allowed_input":
        raise ValueError("browser_use_host.allowed_input_action_unsupported")
    index = params.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError("browser_use_host.index_invalid")
    try:
        input_ref = _INPUT_REF.validate_python(params.get("input_ref"), strict=True)
    except ValidationError as exc:
        raise ValueError("browser_use_host.input_ref_invalid") from exc
    if input_ref not in allowed_inputs:
        if not _allow_unknown:
            raise ValueError("browser_use_host.allowed_input_unknown")
    else:
        value = allowed_inputs[input_ref]
        if value is None or isinstance(value, (dict, list, tuple)):
            raise ValueError("browser_use_host.allowed_input_value_not_scalar")
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("browser_use_host.allowed_input_value_not_scalar") from exc
    return NormalizedVariableAction(
        action_name="click",
        params={"index": index},
        binding_hints=(_binding("row_key", "input", input_ref, kind="skill_input"),),
        variable_outputs={},
    )


def _validated_variable_ref(value: object) -> str:
    try:
        return _VARIABLE_REF.validate_python(value, strict=True)
    except ValidationError as exc:
        raise ValueError("browser_use_host.variable_ref_invalid") from exc


def _copy_json(value: Any) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("browser_use_host.variable_value_not_json") from exc


def _extract_input_bindings(
    raw_refs: object,
    *,
    allowed_inputs: Mapping[str, object],
) -> tuple[tuple[Mapping[str, object], ...], str | None]:
    if not isinstance(raw_refs, list):
        return (), "browser_use_host.extract_input_refs_invalid"
    error: str | None = None
    refs: list[str] = []
    seen: set[str] = set()
    for raw_ref in raw_refs:
        try:
            ref = _INPUT_REF.validate_python(raw_ref, strict=True)
        except ValidationError:
            error = error or "browser_use_host.input_ref_invalid"
            continue
        if ref in seen:
            error = error or "browser_use_host.extract_input_ref_duplicate"
            continue
        seen.add(ref)
        if ref not in allowed_inputs:
            error = error or "browser_use_host.allowed_input_unknown"
            continue
        try:
            _require_json_scalar(allowed_inputs[ref])
        except ValueError:
            error = error or "browser_use_host.allowed_input_value_not_scalar"
            continue
        refs.append(ref)
    bindings = tuple(
        _binding(f"input.{ref}", "input", ref, kind="skill_input")
        for ref in refs
    )
    return bindings, error


def _require_json_scalar(value: object) -> None:
    if value is None or isinstance(value, (dict, list, tuple)):
        raise ValueError("browser_use_host.allowed_input_value_not_scalar")
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("browser_use_host.allowed_input_value_not_scalar") from exc


def _binding(
    name: str, direction: str, variable_ref: str, *, kind: str = "variable"
) -> Mapping[str, object]:
    return {
        "name": name,
        "direction": direction,
        "kind_hint": kind,
        "ref_hint": variable_ref,
        "sensitive": False,
    }


class _VariableTargetAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int
    variable_ref: str


class _ExtractVariableAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    variable_ref: str
    value: JsonValue
    input_refs: list[str] = Field(default_factory=list)


class _LiteralInputAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int
    text: str


class _AllowedInputTargetAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int
    input_ref: Identifier


@dataclass(slots=True)
class _PendingInvocation:
    action_name: str
    params: Mapping[str, object]
    browser_session: object
    registered_action: object | None
    variable_outputs: Mapping[str, object]
    page: object | None = None
    frame_path: tuple[Mapping[str, object], ...] = ()
    target_hint: Mapping[str, object] | None = None
    target_match_count: int = 0
    standard_kwargs: Mapping[str, object] = None  # type: ignore[assignment]
    action_timeout: float | None = None
    preflight_error: str | None = None
    lifecycle_kind: str | None = None
    lifecycle_page_runtime_ref: str | None = None
    lifecycle_frame_runtime_ref: str | None = None
    result: object | None = None


class RecordingBrowserUseTools(Tools):
    """A 0.13.2 Tools boundary that records every actual invocation once."""

    _EXCLUDED = [
        "search",
        "extract",
        "read_file",
        "write_file",
        "replace_file",
        "screenshot",
        "save_as_pdf",
        "upload_file",
    ]

    def __init__(
        self,
        *,
        hosted: object,
        instruction: str,
        allowed_inputs: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(exclude_actions=self._EXCLUDED)
        self._hosted = hosted
        self._instruction = instruction
        self._allowed_inputs = dict(allowed_inputs or {})
        self._reports: list[RecordingRoundReport] = []
        self._pending: dict[str, _PendingInvocation] = {}
        self._target_resolutions: dict[str, TargetResolution] = {}
        input_action = self.registry.registry.actions.pop("input", None)
        if input_action is None:
            raise RuntimeError("browser_use_host.input_action_unavailable")
        self._hidden_input_action = input_action

        @self.registry.action(
            "Fill an element with an explicit literal used by the SOP.",
            param_model=_LiteralInputAction,
        )
        async def input_literal(params: _LiteralInputAction) -> ActionResult:
            del params
            return ActionResult(error="internal literal action was not normalized")

        @self.registry.action(
            "Fill an element with an explicitly named business variable. Never copy a sample value.",
            param_model=_VariableTargetAction,
        )
        async def input_variable(params: _VariableTargetAction) -> ActionResult:
            del params
            return ActionResult(error="internal variable action was not normalized")

        @self.registry.action(
            "Select an option using an explicitly named business variable.",
            param_model=_VariableTargetAction,
        )
        async def select_dropdown_variable(
            params: _VariableTargetAction,
        ) -> ActionResult:
            del params
            return ActionResult(error="internal variable action was not normalized")

        @self.registry.action(
            "Click the row or control selected by an explicitly named business variable.",
            param_model=_VariableTargetAction,
        )
        async def click_variable(params: _VariableTargetAction) -> ActionResult:
            del params
            return ActionResult(error="internal variable action was not normalized")

        @self.registry.action(
            "Click the row or option selected by an explicitly allowed Skill Input reference.",
            param_model=_AllowedInputTargetAction,
        )
        async def click_allowed_input(
            params: _AllowedInputTargetAction,
        ) -> ActionResult:
            del params
            return ActionResult(error="internal allowed input action was not normalized")

        @self.registry.action(
            "Write a JSON value to an explicit business variable reference.",
            param_model=_ExtractVariableAction,
        )
        async def extract_variable(params: _ExtractVariableAction) -> ActionResult:
            return ActionResult(
                extracted_content=json.dumps(params.value, ensure_ascii=False)
            )

        creation = getattr(getattr(hosted, "browser"), "creation")
        self._adapter = BrowserUseRecordingAdapter(
            session=creation,
            executor=self._execute_pending,
            evidence_provider=self._evidence_for,
            target_resolver=lambda action: self._target_resolutions.get(
                action.candidate_id,
                TargetResolution(target_hint=None, match_count=0),
            ),
            allowed_extension_actions=frozenset({"extract_variable"}),
        )

    @property
    def report(self) -> RecordingRoundReport:
        return RecordingRoundReport(
            actual_action_count=sum(item.actual_action_count for item in self._reports),
            candidate_ids=tuple(
                candidate
                for item in self._reports
                for candidate in item.candidate_ids
            ),
            non_sop=tuple(item for report in self._reports for item in report.non_sop),
            invocation_count=sum(item.invocation_count for item in self._reports),
            blocked=tuple(item for report in self._reports for item in report.blocked),
        )

    async def act(self, action: object, browser_session: object, **kwargs: object):
        action_name, raw_params = _one_tool_action(action)
        creation = getattr(getattr(self._hosted, "browser"), "creation")
        normalized: NormalizedVariableAction | None = None
        preflight_error: str | None = None
        if action_name == "input_literal":
            actual_name = "input"
            actual_params = {
                "index": raw_params["index"],
                "text": raw_params["text"],
                "clear": True,
            }
            bindings = (
                {
                    "name": "value",
                    "direction": "input",
                    "kind_hint": "literal",
                    "value": raw_params["text"],
                    "sensitive": False,
                },
            )
            outputs = {}
        elif action_name == "click_allowed_input":
            try:
                normalized = normalize_allowed_input_action(
                    action_name,
                    raw_params,
                    allowed_inputs=self._allowed_inputs,
                )
            except ValueError as exc:
                if str(exc) != "browser_use_host.allowed_input_unknown":
                    raise
                normalized = normalize_allowed_input_action(
                    action_name,
                    raw_params,
                    allowed_inputs=self._allowed_inputs,
                    _allow_unknown=True,
                )
                preflight_error = str(exc)
            actual_name = normalized.action_name
            actual_params = dict(normalized.params)
            bindings = normalized.binding_hints
            outputs = {}
        elif action_name in {
            "input_variable",
            "select_dropdown_variable",
            "click_variable",
            "extract_variable",
        }:
            try:
                normalized = normalize_variable_action(
                    action_name,
                    raw_params,
                    variables=creation.variables,
                    allowed_inputs=self._allowed_inputs,
                )
            except ValueError as exc:
                if action_name != "extract_variable" or str(exc) not in {
                    "browser_use_host.extract_input_refs_invalid",
                    "browser_use_host.input_ref_invalid",
                    "browser_use_host.extract_input_ref_duplicate",
                    "browser_use_host.allowed_input_unknown",
                    "browser_use_host.allowed_input_value_not_scalar",
                }:
                    raise
                normalized = normalize_variable_action(
                    action_name,
                    raw_params,
                    variables=creation.variables,
                    allowed_inputs=self._allowed_inputs,
                    _allow_input_errors=True,
                )
                preflight_error = str(exc)
            actual_name = normalized.action_name
            actual_params = dict(normalized.params)
            bindings = normalized.binding_hints
            outputs = normalized.variable_outputs
            preflight_error = preflight_error or normalized.preflight_error
        else:
            actual_name = action_name
            actual_params = dict(raw_params)
            bindings = ()
            outputs = {}

        port = getattr(getattr(self._hosted, "browser"), "port")
        page = await port.active_page_object()
        main_frame = getattr(page, "main_frame", None)
        if main_frame is None:
            raise RuntimeError("browser_use_host.main_frame_unavailable")
        page_runtime_ref = port.page_runtime_ref(page)
        frame_runtime_ref = port.frame_runtime_ref(main_frame)
        candidate_id = "bu_" + secrets.token_hex(12)
        frame_path: tuple[Mapping[str, object], ...] = ()
        target_hint: Mapping[str, object] | None = None
        match_count = 0
        index = actual_params.get("index")
        if isinstance(index, int) and not isinstance(index, bool):
            state = await browser_session.get_browser_state_summary(
                include_screenshot=False
            )
            selector_map = getattr(getattr(state, "dom_state", None), "selector_map", {})
            node = selector_map.get(index) if isinstance(selector_map, Mapping) else None
            if node is not None:
                try:
                    frame_path, target_hint = semantic_hints_from_browser_use_node(node)
                    match_count = await port.validate_semantic_target(
                        page=page,
                        frame_path=frame_path,
                        target_hint=target_hint,
                    )
                except ValueError:
                    frame_path, target_hint, match_count = (), None, 0
        tab_runtime_refs: dict[str, str] = {}
        if actual_name in {"switch", "close"}:
            tab_runtime_refs = await _tab_runtime_refs(port)
        normalizer = BrowserUseInvocationNormalizer(
            page_registry=creation.pages,
            tab_runtime_resolver=lambda tab: tab_runtime_refs.get(tab)
            or _unsupported("tab"),
            main_frame_resolver=lambda runtime_page: port.page_main_frame_runtime_ref(
                _page_for_runtime(port, runtime_page)
            ),
            asset_ref_resolver=lambda _path: _unsupported("asset"),
            frame_path_resolver=lambda runtime_page, runtime_frame: (
                frame_path
                if runtime_page == page_runtime_ref
                and runtime_frame == frame_runtime_ref
                else port.resolve_frame_path(runtime_page, runtime_frame)
            ),
        )
        recorded = normalizer.normalize(
            actual_name,
            actual_params,
            candidate_id=candidate_id,
            business_intent=_action_instruction(
                self._instruction, action_name, bindings, outputs
            ),
            source_page_runtime_ref=page_runtime_ref,
            source_frame_runtime_ref=frame_runtime_ref,
            binding_hints=bindings,
            target_hint=target_hint,
        )
        self._target_resolutions[candidate_id] = TargetResolution(
            target_hint=target_hint, match_count=match_count
        )
        registered = (
            self._hidden_input_action
            if actual_name == "input"
            else self.registry.registry.actions.get(actual_name)
        )
        self._pending[candidate_id] = _PendingInvocation(
            action_name=actual_name,
            params=actual_params,
            browser_session=browser_session,
            registered_action=registered,
            variable_outputs=outputs,
            page=page,
            frame_path=frame_path,
            target_hint=target_hint,
            target_match_count=match_count,
            standard_kwargs={
                key: value
                for key, value in kwargs.items()
                if key
                in {
                    "page_extraction_llm",
                    "sensitive_data",
                    "available_file_paths",
                    "file_system",
                    "extraction_schema",
                }
            },
            action_timeout=(
                float(kwargs["action_timeout"])
                if isinstance(kwargs.get("action_timeout"), (int, float))
                and not isinstance(kwargs.get("action_timeout"), bool)
                and float(kwargs["action_timeout"]) > 0
                else None
            ),
            preflight_error=preflight_error,
            lifecycle_kind=(
                "page_activated"
                if actual_name == "switch"
                else "page_closed" if actual_name == "close" else None
            ),
            lifecycle_page_runtime_ref=(
                tab_runtime_refs.get(str(actual_params.get("tab_id")))
                if actual_name in {"switch", "close"}
                else None
            ),
            lifecycle_frame_runtime_ref=frame_runtime_ref,
        )
        try:
            report = await self._adapter.record_round((recorded,))
            self._reports.append(report)
            return self._pending[candidate_id].result
        finally:
            self._pending.pop(candidate_id, None)
            self._target_resolutions.pop(candidate_id, None)

    async def _execute_pending(self, action: object) -> object:
        pending = self._pending[getattr(action, "candidate_id")]
        registered = pending.registered_action
        if pending.preflight_error is not None:
            result = ActionResult(error=pending.preflight_error)
            pending.result = result
            return result
        try:
            port = getattr(getattr(self._hosted, "browser"), "port")
            dispatch_scope = getattr(port, "action_dispatch_scope", None)
            if not callable(dispatch_scope) or pending.page is None:
                raise RuntimeError("browser_use_host.action_dispatch_scope_unavailable")
            target = SimpleNamespace(
                page=pending.page,
                page_runtime_ref=getattr(action, "runtime_page_ref"),
                frame_runtime_ref=getattr(action, "runtime_frame_ref"),
            )
            async with dispatch_scope(target):
                if registered is None:
                    result = ActionResult(error="Action is not registered")
                else:
                    validated = registered.param_model(**pending.params)
                    returned = registered.function(
                        params=validated,
                        browser_session=pending.browser_session,
                        **dict(pending.standard_kwargs or {}),
                    )
                    if inspect.isawaitable(returned):
                        result = (
                            await asyncio.wait_for(
                                returned, timeout=pending.action_timeout
                            )
                            if pending.action_timeout is not None
                            else await returned
                        )
                    else:
                        result = returned
                    if isinstance(result, str):
                        result = ActionResult(extracted_content=result)
                    elif result is None:
                        result = ActionResult()
                    elif not isinstance(result, ActionResult):
                        result = ActionResult(error="Tool returned an invalid result")
        except Exception as exc:
            result = ActionResult(error=f"{type(exc).__name__}: {exc}")
        pending.result = result
        if (
            pending.lifecycle_kind is not None
            and pending.lifecycle_page_runtime_ref is not None
            and getattr(result, "error", None) is None
            and getattr(result, "success", None) is not False
        ):
            from .browser_session import HostBrowserEvent

            getattr(self._hosted, "browser").handle_event(
                HostBrowserEvent(
                    kind=pending.lifecycle_kind,
                    observed_at=datetime.now(timezone.utc),
                    source_page_runtime_ref=(
                        getattr(action, "runtime_page_ref")
                    ),
                    source_frame_runtime_ref=(
                        getattr(action, "runtime_frame_ref")
                    ),
                    runtime_page_ref=pending.lifecycle_page_runtime_ref,
                )
            )
        return result

    async def _evidence_for(self, action: object, result: object) -> Mapping[str, object]:
        pending = self._pending[getattr(action, "candidate_id")]
        if pending.action_name in {
            "done",
            "wait",
            "observe",
            "search_page",
            "find_elements",
            "find_text",
            "dropdown_options",
        }:
            return {}
        if pending.variable_outputs:
            return {"variables": dict(pending.variable_outputs)}
        error = getattr(result, "error", None)
        success = getattr(result, "success", None)
        if error is not None or success is False:
            return {"completed": False}
        if pending.action_name == "navigate":
            state = await pending.browser_session.get_browser_state_summary(
                include_screenshot=False
            )
            expected = str(pending.params.get("url", ""))
            return {"url_reached": str(getattr(state, "url", "")) == expected}
        if (
            pending.action_name in {"click", "input", "select_dropdown"}
            and pending.target_match_count == 1
            and pending.target_hint is not None
            and pending.page is not None
        ):
            port = getattr(getattr(self._hosted, "browser"), "port")
            expected = (
                action.params.get("text")
                if pending.action_name == "input"
                else action.params.get("option")
                if pending.action_name == "select_dropdown"
                else None
            )
            return await port.semantic_action_evidence(
                action_name=pending.action_name,
                page=pending.page,
                frame_path=pending.frame_path,
                target_hint=pending.target_hint,
                expected=expected,
            )
        if pending.action_name == "switch":
            runtime_ref = pending.lifecycle_page_runtime_ref
            if runtime_ref is None:
                return {"activated_page_ref": ""}
            page_ref = getattr(getattr(self._hosted, "browser"), "creation").pages.resolve(
                runtime_ref
            )
            return {"activated_page_ref": page_ref}
        if pending.action_name == "close":
            return {"closed_page_ref": action.page_ref}
        if pending.action_name == "send_keys":
            return {"dispatched": True}
        return {"completed": True}


def _one_tool_action(action: object) -> tuple[str, dict[str, object]]:
    dump = getattr(action, "model_dump", None)
    if not callable(dump):
        raise TypeError("browser_use_host.action_invalid")
    payload = dump(exclude_unset=True, exclude_none=True)
    if "root" in payload and isinstance(payload["root"], Mapping):
        payload = payload["root"]
    selected = [(name, value) for name, value in payload.items() if value is not None]
    if len(selected) != 1:
        raise ValueError("browser_use_host.actual_action_count_invalid")
    name, params = selected[0]
    if isinstance(params, BaseModel):
        params = params.model_dump(mode="python", exclude_none=True)
    if not isinstance(params, Mapping):
        raise TypeError("browser_use_host.action_params_invalid")
    return str(name), dict(params)


def _unsupported(kind: str):
    raise ValueError(f"browser_use_host.{kind}_unsupported")


def _page_for_runtime(port: object, runtime_ref: str) -> object:
    pages = tuple(getattr(getattr(port, "context"), "pages", ()) or ())
    matches = [page for page in pages if port.page_runtime_ref(page) == runtime_ref]
    if len(matches) != 1:
        raise ValueError("browser_use_host.runtime_page_ambiguous")
    return matches[0]


def _action_instruction(
    round_instruction: str,
    action_name: str,
    bindings: tuple[Mapping[str, object], ...],
    outputs: Mapping[str, object],
) -> str:
    refs = [str(item["ref_hint"]) for item in bindings if item.get("ref_hint")]
    return json.dumps(
        {
            "round_instruction": round_instruction,
            "current_action": action_name,
            "business_variable_refs": refs,
            "must_return_variable_refs": sorted(outputs),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


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


def build_agent_task(
    hosted: object,
    request: AgentInstructionRequest,
    *,
    page: object | None = None,
) -> str:
    creation = getattr(getattr(hosted, "browser"), "creation")
    variables = {
        ref: creation.variables.read(ref) for ref in request.required_variable_refs
    }
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
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)


async def _model_for(owner_id: str) -> ChatOpenAI:
    from backend.models import resolve_default_model_config

    config = await resolve_default_model_config(owner_id)
    if not isinstance(config, Mapping):
        raise RuntimeError("browser_use_host.model_unavailable")
    model = config.get("model_name")
    api_key = config.get("api_key")
    if not isinstance(model, str) or not model or not isinstance(api_key, str) or not api_key:
        raise RuntimeError("browser_use_host.model_invalid")
    base_url = config.get("base_url")
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url if isinstance(base_url, str) and base_url else None,
    )


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
    model = await model_factory(str(getattr(hosted, "owner_id")))
    tools = RecordingBrowserUseTools(
        hosted=hosted,
        instruction=request.instruction,
        allowed_inputs=request.allowed_inputs,
    )
    browser_session = browser_session_factory(cdp_url=cdp_url, keep_alive=True)
    await browser_session.start()
    try:
        page = await port.active_page_object()
        await _focus_exact_page(browser_session, page)
        agent = agent_factory(
            task=build_agent_task(hosted, request, page=page),
            llm=model,
            browser_session=browser_session,
            tools=tools,
            use_vision=False,
            max_actions_per_step=1,
            max_history_items=2,
            enable_signal_handler=False,
        )
        history = await agent.run(max_steps=40)
        if history.is_done() is not True or history.is_successful() is not True:
            raise RuntimeError("browser_use_host.instruction_failed")
        report = tools.report
        if report.invocation_count != report.actual_action_count + len(report.blocked):
            raise RuntimeError("browser_use_host.action_accounting_incomplete")
        return report
    finally:
        await browser_session.stop()


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
        required_paths: Mapping[str, tuple[str, ...]],
    ) -> Mapping[str, object]:
        del target
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
        model = await model_factory(str(getattr(hosted, "owner_id")))
        fields = {name: (JsonValue, ...) for name in output_names}
        output_model = create_model("RuntimeAgentOutputs", **fields) if fields else None
        task = json.dumps(
            {
                "instruction": instruction,
                "inputs": dict(inputs),
                "required_outputs": list(output_names),
                "required_paths": {
                    name: list(paths) for name, paths in required_paths.items()
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        session = browser_session_factory(cdp_url=cdp_url, keep_alive=True)
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
                max_actions_per_step=1,
                max_history_items=2,
                enable_signal_handler=False,
            )
            history = await agent.run(max_steps=30)
            if history.is_done() is not True or history.is_successful() is not True:
                raise RuntimeError("runtime_agent.instruction_failed")
            if output_model is None:
                return {}
            structured = history.get_structured_output(output_model)
            if structured is None:
                raise RuntimeError("runtime_agent.output_missing")
            return structured.model_dump(mode="python")
        finally:
            await session.stop()

    return backend


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
    "NormalizedVariableAction",
    "RecordingBrowserUseTools",
    "build_agent_task",
    "build_runtime_agent_backend",
    "execute_browser_use_instruction",
    "normalize_allowed_input_action",
    "normalize_variable_action",
    "run_compiled_skill_with_agent",
    "semantic_hints_from_browser_use_node",
]
