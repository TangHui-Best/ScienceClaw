from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import json
import linecache
import logging
import os
import re
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from pydantic import BaseModel, Field

from .assistant_runtime import build_page_snapshot
from .frame_selectors import build_frame_path
from .snapshot_compression import compact_recording_snapshot
from .trace_models import (
    RPAAcceptedTrace,
    RPAAIExecution,
    RPALocatorStabilityCandidate,
    RPALocatorStabilityMetadata,
    RPAPageState,
    RPATraceDiagnostic,
    RPATraceType,
)
from .trace_locator_utils import (
    locator_is_replay_safe_for_region_extract,
    normalize_locator,
)


logger = logging.getLogger(__name__)


_GENERATED_CODE_FILENAME = "<recording_runtime_agent>"
_RANDOM_LIKE_ATTR_RE = re.compile(r"(?i)(?:[a-z]+[-_])?[a-z0-9]{6,}[a-z][a-z0-9]*")
_DOWNLOAD_EVENT_DRAIN_TIMEOUT_S = 0.5
_RECORDING_PLANNER_MIN_OUTPUT_TOKENS = 8192


class _DownloadEventCapture:
    def __init__(self, page: Any):
        self.page = page
        self.events: List[Dict[str, Any]] = []
        self._observed: Optional[asyncio.Future] = None
        self._attached = False

    def start(self) -> None:
        self._observed = asyncio.get_running_loop().create_future()
        page_on = getattr(self.page, "on", None)
        if not callable(page_on):
            return
        try:
            page_on("download", self._on_download)
            self._attached = True
        except Exception:
            self._attached = False

    def _on_download(self, download: Any) -> None:
        self.events.append(
            {
                "filename": str(getattr(download, "suggested_filename", "") or ""),
                "url": str(getattr(self.page, "url", "") or ""),
            }
        )
        if self._observed is not None and not self._observed.done():
            self._observed.set_result(True)

    async def drain(self, *, should_wait: bool) -> None:
        if not self._attached:
            return
        await asyncio.sleep(0)
        if self.events or not should_wait or self._observed is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(self._observed),
                timeout=_DOWNLOAD_EVENT_DRAIN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            pass

    def close(self) -> None:
        if not self._attached:
            return
        remover = getattr(self.page, "remove_listener", None) or getattr(self.page, "off", None)
        if callable(remover):
            try:
                remover("download", self._on_download)
            except Exception:
                pass

    def signal(self) -> Optional[Dict[str, Any]]:
        if not self.events:
            return None
        download_signal = dict(self.events[0])
        download_signal["count"] = len(self.events)
        if len(self.events) > 1:
            download_signal["files"] = list(self.events)
        return download_signal


RECORDING_RUNTIME_SYSTEM_PROMPT = """You operate exactly one RPA recording command.
Return JSON only.
Schema:
{
  "description": "short user-facing action summary",
  "action_type": "run_python|extract_snapshot",
  "expected_effect": "extract|navigate|click|fill|mixed",
  "allow_empty_output": false,
  "output_key": "optional_ascii_snake_case_result_key",
  "code": "async def run(page, results): ...",
  "source": "detail_views",
  "section_title": "optional snapshot section title",
  "frame_path": "optional iframe selector chain for extract_snapshot",
  "fields": "optional structured fields for extract_snapshot",
  "preserve_runtime_ai": false,
  "semantic_intent": "optional reason when runtime AI must re-evaluate current page candidates"
}
Rules:
- Complete only the current user command, not the full SOP.
- Return action_type="run_python" unless a simple goto/click/fill action is clearly enough.
- expected_effect describes the browser-visible outcome required by the user's current command.
- Use expected_effect="navigate" when the user asks to open, go to, enter, visit, or navigate to a target.
- Use expected_effect="extract" when the user only asks to find, collect, summarize, or return data without opening it.
- Set preserve_runtime_ai=true when the command requires semantic judgment over current page candidates at replay time, such as selecting the most relevant, best matching, recommended, highest risk, or most suitable item.
- Do not set preserve_runtime_ai for a simple deterministic click/fill/goto where the recorded locator or value is the intended reusable behavior.
- If code is returned, it must define async def run(page, results).
- Use action_type="extract_snapshot" only when the requested extract-only data is already present in snapshot.detail_views fields.
- For extract_snapshot, return the relevant observed detail fields in the plan itself, including the detail view frame_path when present; do not generate Python code and do not reference `snapshot` inside `run()`.
- For snapshot.mode="region_scoped_snapshot", selected-region evidence is the authoritative scope. If you use extract_snapshot, fields must contain labels copied from selected region evidence; empty values are valid unless the field is explicitly required or the user's task requires non-empty output.
- Do not generate replay code that locates selected free text by the exact observed text value. Observed selected text is evidence, not a stable replay selector.
- If payload.plan_validation is present, correct the failed plan contract issue before execution; do not repeat a failed extract_snapshot plan without fields.
- `snapshot` is planner-only evidence. Generated Python can access only `page` and `results`.
- 结果返回规则：
  - `results` 是普通 Python dict，只包含之前已成功步骤的输出结果。
  - 可以从 `results` 读取历史结果，用于跨步骤引用、整合、过滤、改写或汇总。
  - 不要在 `run()` 内原地修改 `results`，也不要把当前步骤输出直接写入 `results`。
  - 如果需要基于已有结果产生新结果，应读取 `results`，使用局部变量构造新的 Python 值，并通过 `return` 返回该新值。
  - 禁止调用 `results.set(...)`、`results.write(...)`、`results.update(...)` 来保存当前步骤结果。
  - 禁止通过 `results[...] = ...` 保存当前步骤结果。
  - 当前步骤产生的数据只能通过 `return` 从 `run(page, results)` 返回。
  - `output_key` 只是给后置 trace compiler 使用的元数据，不要在生成代码中根据 `output_key` 实现结果存储。
  - 最终 `_results[output_key] = _result` 由 skill 编译阶段自动生成，录制阶段代码不要实现这件事。
- Use Python Playwright async APIs.
- Prefer Playwright locators and page.locator/query_selector_all over page.evaluate.
- Avoid page.evaluate unless the snippet is short, read-only, and necessary.
- Do not include shell, filesystem, network requests outside the current browser page, or infinite loops.
- For search-engine tasks, if the user's goal is to search/open results, prefer navigating to the results URL with an encoded query. If the user explicitly asks to fill a search box, first target visible, enabled, editable input candidates instead of filling hidden DOM matches.
- Do not leave the browser on API, JSON, raw, or other machine endpoints after an extract-only command.
- For extract-only commands, prefer user-facing pages and restore the most recent user-facing page after any temporary helper navigation.
- For extract-only commands, prefer snapshot.expanded_regions and snapshot.sampled_regions before broad DOM scans.
- For count/stat/value extraction, do not accept a broad multi-match locator plus `.first` as the default strategy.
  Inspect visible candidates, prefer candidates whose text shape matches the requested value, and only return empty data
  when the user explicitly allows empty output.
- Use the region title, heading, or catalogue summary as context when it matches the requested area.
- If an expanded region is a label_value_group and the user asks for field names or values, keep extraction focused on that region or supporting locator evidence instead of scanning every table.
- Avoid treating tables as the default fallback for field extraction when a more relevant label_value_group is present.
- snapshot.region_catalogue is page context only.
- Structured snapshot views:
  - For table/list/grid tasks, inspect `snapshot.table_views` before generic `expanded_regions`.
  - `table_views[].columns` describes column ids, headers, and inferred roles.
  - `table_views[].rows[].cells` describes row-local cell text and row-local actions.
  - For ordinal table tasks, prefer row-relative and column-relative Playwright locators.
  - Do not use observed row text as the primary selector when the instruction is ordinal.
  - For detail extraction, inspect `snapshot.detail_views` before scanning generic text or tables.
  - `detail_views[].fields` preserves label, value, data_prop, required, visible, and value_kind.
  - Treat hidden fields as diagnostic unless the user explicitly asks for hidden/default/internal values.
  - For form fill/edit tasks, inspect `snapshot.form_views` before generic text, tables, or summary regions.
  - `form_views[].fields[].control.locator` is executable locator evidence for fillable controls.
  - Do not turn summary text into placeholder, label, name, or CSS selectors unless a form/detail/actionable locator explicitly exposes that attribute.
- Snapshot 结构契约：
  - `evidence` 是页面事实，用于理解当前区域的文本、字段、表头、样例行或可操作项。
  - `locator_hints`、`locator`、`label_locator`、`value_locator`、`actions[].locator` 是可执行定位线索，生成 Playwright 代码时应优先使用这些字段。
  - `ref`、`internal_ref`、`region_id`、`container_id`、`node_id` 是系统内部引用，只用于诊断和回溯 snapshot，不是 DOM id、CSS selector 或 Playwright locator。
  - 不要把内部引用改写成 `#...`、`[id=...]` 或其他 selector。
  - 对表格提取任务，优先使用 `locator_hints`、可见表头、标题文本或角色语义来定位表格，不要使用内部引用作为 selector。
- Do not include a separate done-check.
- For run_python click/fill commands, return action evidence such as `{"action_performed": True, "action_type": "fill", "filled_value": value}` after the Playwright action completes.
- If extracting data, return structured JSON-serializable Python values.
- For extract-only commands, preserve empty strings, empty lists, and empty tables as factual outputs unless the user explicitly requires non-empty results.
- Set allow_empty_output=false only when the user explicitly requires a non-empty result; otherwise empty strings, empty lists, and empty tables may be valid extract outputs.
- During repair, treat raw error logs and current page facts as authoritative. Any failure_analysis.hint is advisory only.
- 修复规则：
  - 修复时必须优先参考原始错误日志、异常类型、traceback 行号和当前页面事实。
  - 修复前先判断失败类型：如果失败来自 Python 代码错误，应优先修复对应代码行；如果失败来自页面状态、定位器、空数据或目标区域选择错误，再调整 selector 或取数策略。
  - 修复时应保持用户原始目标不变，不要把一次局部代码错误扩展成无关的页面流程重写。
- During repair after a fill/click actionability failure, inspect the page after failure and visible candidates before retrying the selector.
"""


class RecordingAgentResult(BaseModel):
    success: bool
    trace: Optional[RPAAcceptedTrace] = None
    diagnostics: List[RPATraceDiagnostic] = Field(default_factory=list)
    output_key: Optional[str] = None
    output: Any = None
    message: str = ""


class RecordingPlannerContractError(ValueError):
    def __init__(self, message: str, *, raw_output: str = "", cause: Optional[BaseException] = None):
        super().__init__(message)
        self.raw_output = raw_output
        self.llm_call: Dict[str, Any] = {}
        self.__cause__ = cause


Planner = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
Executor = Callable[[Any, Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]


class RecordingRuntimeAgent:
    def __init__(
        self,
        planner: Optional[Planner] = None,
        executor: Optional[Executor] = None,
        model_config: Optional[Dict[str, Any]] = None,
    ):
        self.planner = planner or self._default_planner
        self.executor = executor or self._default_executor
        self.model_config = model_config
        self._planner_llm_calls: List[Dict[str, Any]] = []

    async def run(
        self,
        *,
        page: Any,
        instruction: str,
        runtime_results: Optional[Dict[str, Any]] = None,
        debug_context: Optional[Dict[str, Any]] = None,
        region_context: Optional[Dict[str, Any]] = None,
    ) -> RecordingAgentResult:
        runtime_results = runtime_results if runtime_results is not None else {}
        debug_context = dict(debug_context or {})
        before = await _page_state(page)
        region_scope = _region_scope_from_context(region_context)
        snapshot = await _capture_page_snapshot(page, region_scope=region_scope)
        compact_snapshot = _compact_snapshot_for_runtime(snapshot, instruction, region_scope=region_scope or None)
        compact_region_context = _compact_region_context(region_context)
        raw_region_evidence = _raw_region_evidence(region_context)
        payload = {
            "instruction": instruction,
            "page": before.model_dump(mode="json"),
            "snapshot": compact_snapshot,
            "runtime_results": runtime_results,
        }
        snapshot_extra: Dict[str, Any] = {}
        if raw_region_evidence:
            snapshot_extra["raw_region_evidence"] = raw_region_evidence
        if region_scope:
            snapshot_extra["region_scope"] = region_scope
            snapshot_extra["region_scoped_snapshot"] = compact_snapshot
        if compact_region_context:
            snapshot_extra["planner_region_context"] = compact_region_context
            snapshot_extra["region_context_decision"] = {}
        _write_recording_snapshot_debug(
            "initial",
            instruction=instruction,
            page_state=before.model_dump(mode="json"),
            raw_snapshot=snapshot,
            compact_snapshot=compact_snapshot,
            runtime_results=runtime_results,
            debug_context=debug_context,
            extra=snapshot_extra or None,
        )

        first_plan = None
        if not compact_region_context:
            first_plan = _build_table_ordinal_overlay_plan(instruction, snapshot)
            if not first_plan:
                first_plan = _build_ordinal_overlay_plan(instruction, snapshot)
        first_planner_call_index = len(self._planner_llm_calls)
        if not first_plan:
            try:
                first_plan = await self.planner(payload)
            except Exception as exc:
                _write_recording_planner_failure_debug(
                    "initial",
                    instruction=instruction,
                    page_state=before.model_dump(mode="json"),
                    raw_snapshot=snapshot,
                    compact_snapshot=compact_snapshot,
                    exception=exc,
                    model_config=self.model_config,
                    debug_context=debug_context,
                )
                return RecordingAgentResult(
                    success=False,
                    diagnostics=[
                        _planner_contract_diagnostic(
                            exc,
                            stage="initial",
                            model_config=self.model_config,
                        )
                    ],
                    message="Recording planner failed to return a valid plan.",
                )
        if compact_region_context:
            plan_validation_error = _selected_region_extract_plan_validation_error(first_plan)
            if plan_validation_error:
                validation_payload = _build_region_plan_validation_payload(payload, first_plan, plan_validation_error)
                try:
                    first_plan = await self.planner(validation_payload)
                except Exception as exc:
                    return RecordingAgentResult(
                        success=False,
                        diagnostics=[
                            _planner_contract_diagnostic(
                                exc,
                                stage="initial_plan_validation",
                                model_config=self.model_config,
                            )
                        ],
                        message="Recording planner failed to correct an invalid selected-region plan.",
                    )
        first_llm_call = self._planner_llm_call_since(first_planner_call_index)
        first_result = await self.executor(page, first_plan, runtime_results)
        first_result = await _ensure_expected_effect(
            page=page,
            instruction=instruction,
            plan=first_plan,
            result=first_result,
            before=before,
        )
        _write_recording_attempt_debug(
            "initial_attempt",
            instruction=instruction,
            page_state=before.model_dump(mode="json"),
            plan=first_plan,
            execution_result=first_result,
            failure_analysis=None if first_result.get("success") else _known_failure_analysis(first_result.get("error")),
            debug_context=debug_context,
        )
        if first_result.get("success"):
            trace = await self._accepted_trace(
                page,
                instruction,
                first_plan,
                first_result,
                before,
                repair_attempted=False,
                snapshot=snapshot,
                compact_snapshot=compact_snapshot,
                region_context=compact_region_context,
                region_scope=region_scope,
            )
            return RecordingAgentResult(
                success=True,
                trace=trace,
                output_key=trace.output_key,
                output=trace.output,
                message="Recording command completed.",
            )

        failed_page = await _page_state(page)
        failed_snapshot = await _capture_page_snapshot(page, region_scope=region_scope)
        compact_failed_snapshot = _compact_snapshot_for_runtime(
            failed_snapshot,
            instruction,
            region_scope=region_scope or None,
        )
        repair_snapshot = compact_failed_snapshot
        first_error = str(first_result.get("error") or "recording command failed")
        first_error_type = str(first_result.get("error_type") or "").strip()
        first_traceback = str(first_result.get("traceback") or "").strip()
        first_failure_analysis = _classify_recording_failure(first_error)
        first_known_failure_analysis = _known_failure_analysis(first_error)
        logger.warning(
            "[RPA] recording command first attempt failed type=%s error=%s",
            first_failure_analysis.get("type", "unknown"),
            first_error[:300],
        )
        repair_snapshot_extra = {
            "failed_plan": _safe_jsonable(first_plan),
            "error": first_error,
        }
        if raw_region_evidence:
            repair_snapshot_extra["raw_region_evidence"] = raw_region_evidence
        if region_scope:
            repair_snapshot_extra["region_scope"] = region_scope
            repair_snapshot_extra["region_scoped_snapshot"] = compact_failed_snapshot
        if compact_region_context:
            repair_snapshot_extra["planner_region_context"] = compact_region_context
            repair_snapshot_extra["region_context_decision"] = _region_context_decision_signal(
                first_plan,
                compact_region_context,
            )
        if first_error_type:
            repair_snapshot_extra["error_type"] = first_error_type
        if first_traceback:
            repair_snapshot_extra["traceback"] = first_traceback
        if first_known_failure_analysis:
            repair_snapshot_extra["failure_analysis"] = first_known_failure_analysis
        _write_recording_snapshot_debug(
            "repair",
            instruction=instruction,
            page_state=failed_page.model_dump(mode="json"),
            raw_snapshot=failed_snapshot,
            compact_snapshot=compact_failed_snapshot,
            runtime_results=runtime_results,
            debug_context=debug_context,
            extra=repair_snapshot_extra,
        )
        diagnostic_raw = {
            "plan": _safe_jsonable(first_plan),
            "result": _safe_jsonable(first_result),
            "page_after_failure": failed_page.model_dump(mode="json"),
            "snapshot_after_failure": _safe_jsonable(repair_snapshot),
        }
        if first_llm_call:
            diagnostic_raw["llm_call"] = _safe_jsonable(first_llm_call)
        if first_error_type:
            diagnostic_raw["error_type"] = first_error_type
        if first_traceback:
            diagnostic_raw["traceback"] = first_traceback
        if first_known_failure_analysis:
            diagnostic_raw["failure_analysis"] = first_known_failure_analysis
        diagnostics = [
            RPATraceDiagnostic(
                source="ai",
                message=first_error,
                raw=diagnostic_raw,
            )
        ]

        repair_context = {
            "error": first_error,
            "failed_plan": first_plan,
            "page_after_failure": failed_page.model_dump(mode="json"),
            "snapshot_after_failure": repair_snapshot,
        }
        if first_error_type:
            repair_context["error_type"] = first_error_type
        if first_traceback:
            repair_context["traceback"] = first_traceback
        if first_known_failure_analysis:
            repair_context["failure_analysis"] = first_known_failure_analysis
        repair_payload = {
            **payload,
            "repair": repair_context,
        }
        repair_planner_call_index = len(self._planner_llm_calls)
        try:
            repair_plan = await self.planner(repair_payload)
        except Exception as exc:
            _write_recording_planner_failure_debug(
                "repair",
                instruction=instruction,
                page_state=failed_page.model_dump(mode="json"),
                raw_snapshot=failed_snapshot,
                compact_snapshot=compact_failed_snapshot,
                exception=exc,
                model_config=self.model_config,
                debug_context=debug_context,
            )
            diagnostics.append(
                _planner_contract_diagnostic(
                    exc,
                    stage="repair",
                    model_config=self.model_config,
                )
            )
            return RecordingAgentResult(
                success=False,
                diagnostics=diagnostics,
                message="Recording planner failed to return a valid repair plan.",
            )
        if compact_region_context:
            repair_plan_validation_error = _selected_region_extract_plan_validation_error(repair_plan)
            if repair_plan_validation_error:
                validation_payload = _build_region_plan_validation_payload(
                    repair_payload,
                    repair_plan,
                    repair_plan_validation_error,
                )
                try:
                    repair_plan = await self.planner(validation_payload)
                except Exception as exc:
                    diagnostics.append(
                        _planner_contract_diagnostic(
                            exc,
                            stage="repair_plan_validation",
                            model_config=self.model_config,
                        )
                    )
                    return RecordingAgentResult(
                        success=False,
                        diagnostics=diagnostics,
                        message="Recording planner failed to correct an invalid selected-region repair plan.",
                    )
        repair_llm_call = self._planner_llm_call_since(repair_planner_call_index)
        repair_result = await self.executor(page, repair_plan, runtime_results)
        repair_result = await _ensure_expected_effect(
            page=page,
            instruction=instruction,
            plan=repair_plan,
            result=repair_result,
            before=before,
        )
        _write_recording_attempt_debug(
            "repair_attempt",
            instruction=instruction,
            page_state=failed_page.model_dump(mode="json"),
            plan=repair_plan,
            execution_result=repair_result,
            failure_analysis=None if repair_result.get("success") else _known_failure_analysis(repair_result.get("error")),
            debug_context=debug_context,
        )
        if repair_result.get("success"):
            trace = await self._accepted_trace(
                page,
                instruction,
                repair_plan,
                repair_result,
                before,
                repair_attempted=True,
                snapshot=failed_snapshot,
                compact_snapshot=compact_failed_snapshot,
                region_context=compact_region_context,
                region_scope=region_scope,
            )
            return RecordingAgentResult(
                success=True,
                trace=trace,
                diagnostics=diagnostics,
                output_key=trace.output_key,
                output=trace.output,
                message="Recording command completed after one repair.",
            )

        repair_error = str(repair_result.get("error") or "recording command repair failed")
        repair_error_type = str(repair_result.get("error_type") or "").strip()
        repair_traceback = str(repair_result.get("traceback") or "").strip()
        repair_failure_analysis = _classify_recording_failure(repair_error)
        repair_known_failure_analysis = _known_failure_analysis(repair_error)
        logger.warning(
            "[RPA] recording command repair failed type=%s error=%s",
            repair_failure_analysis.get("type", "unknown"),
            repair_error[:300],
        )
        repair_diagnostic_raw = {
            "plan": _safe_jsonable(repair_plan),
            "result": _safe_jsonable(repair_result),
        }
        if repair_llm_call:
            repair_diagnostic_raw["llm_call"] = _safe_jsonable(repair_llm_call)
        if repair_error_type:
            repair_diagnostic_raw["error_type"] = repair_error_type
        if repair_traceback:
            repair_diagnostic_raw["traceback"] = repair_traceback
        if repair_known_failure_analysis:
            repair_diagnostic_raw["failure_analysis"] = repair_known_failure_analysis
        diagnostics.append(
            RPATraceDiagnostic(
                source="ai",
                message=repair_error,
                raw=repair_diagnostic_raw,
            )
        )
        return RecordingAgentResult(
            success=False,
            diagnostics=diagnostics,
            message="Recording command failed after one repair.",
        )

    async def _accepted_trace(
        self,
        page: Any,
        instruction: str,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        before: RPAPageState,
        *,
        repair_attempted: bool,
        snapshot: Optional[Dict[str, Any]] = None,
        compact_snapshot: Optional[Dict[str, Any]] = None,
        region_context: Optional[Dict[str, Any]] = None,
        region_scope: Optional[Dict[str, Any]] = None,
    ) -> RPAAcceptedTrace:
        after = await _page_state(page)
        output = result.get("output")
        output_key = _normalize_result_key(plan.get("output_key"))
        locator_stability = _build_locator_stability_metadata(plan, snapshot or {})
        signals = _merge_runtime_ai_signal(dict(result.get("signals") or {}), plan)
        compact_region_context = dict(region_context or {})
        if compact_region_context:
            signals["region_selection"] = _region_selection_signal(compact_region_context)
            signals["region_context_decision"] = _region_context_decision_signal(plan, compact_region_context)
            region_text_extract = _region_text_extract_signal(plan, compact_snapshot or {}, compact_region_context)
            if region_text_extract:
                signals["region_text_extract"] = region_text_extract
            else:
                selected_text_extract = _selected_region_text_extract_signal(plan, result, compact_region_context)
                if selected_text_extract:
                    signals["selected_region_text_extract"] = selected_text_extract
        if _normalize_bool(plan.get("allow_empty_output")):
            output_contract = signals.get("output_contract") if isinstance(signals.get("output_contract"), dict) else {}
            signals["output_contract"] = {**output_contract, "allow_empty": True}
        return RPAAcceptedTrace(
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            user_instruction=instruction,
            description=str(plan.get("description") or instruction),
            before_page=before,
            after_page=after,
            signals=signals,
            region_context=compact_region_context,
            region_scope=dict(region_scope or {}),
            output_key=output_key,
            output=output,
            ai_execution=RPAAIExecution(
                language="snapshot" if str(plan.get("action_type") or "").strip() == "extract_snapshot" else "python",
                code=_trace_replay_code_from_plan(plan),
                output=output,
                error=result.get("error"),
                repair_attempted=repair_attempted,
            ),
            locator_stability=locator_stability,
        )

    async def _default_planner(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from backend.config import settings
        from backend.deepagent.engine import get_llm_model
        from langchain_core.messages import HumanMessage, SystemMessage

        planner_max_tokens = max(int(getattr(settings, "max_tokens", 0) or 0), _RECORDING_PLANNER_MIN_OUTPUT_TOKENS)
        model = get_llm_model(
            config=self.model_config,
            max_tokens_override=planner_max_tokens,
            streaming=False,
        )
        messages = [
            SystemMessage(content=RECORDING_RUNTIME_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
        ]
        llm_request = _build_planner_llm_request_summary(
            model=model,
            messages=messages,
            model_config=self.model_config,
        )
        response = await model.ainvoke(messages)
        response_text = _extract_text(response)
        llm_call = {
            "request": llm_request,
            "response": _text_diagnostic(response_text, limit=8000),
        }
        self._planner_llm_calls.append(llm_call)
        _log_planner_llm_call(llm_call)
        try:
            return _parse_json_object(response_text)
        except Exception as exc:
            try:
                setattr(exc, "llm_call", llm_call)
            except Exception:
                pass
            raise

    def _planner_llm_call_since(self, start_index: int) -> Dict[str, Any]:
        if len(self._planner_llm_calls) <= start_index:
            return {}
        return self._planner_llm_calls[-1]

    async def _default_executor(self, page: Any, plan: Dict[str, Any], runtime_results: Dict[str, Any]) -> Dict[str, Any]:
        action_type = str(plan.get("action_type") or "run_python").strip()
        try:
            if action_type == "goto":
                url = str(plan.get("url") or plan.get("target_url") or "")
                if not url:
                    return {"success": False, "error": "goto plan missing url", "output": ""}
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_load_state("domcontentloaded")
                return {
                    "success": True,
                    "output": {"url": getattr(page, "url", url)},
                    "effect": {"type": "navigate", "url": getattr(page, "url", url)},
                }

            if action_type == "click":
                selector = str(plan.get("selector") or "")
                if not selector:
                    return {"success": False, "error": "click plan missing selector", "output": ""}
                download_capture = _DownloadEventCapture(page)
                download_capture.start()
                try:
                    await page.locator(selector).first.click()
                    await download_capture.drain(should_wait=True)
                finally:
                    download_capture.close()
                response = {
                    "success": True,
                    "output": "clicked",
                    "effect": {"type": "click", "action_performed": True},
                }
                download_signal = download_capture.signal()
                if download_signal:
                    response["signals"] = {"download": download_signal}
                    response["effect"] = {"type": "download", "action_performed": True}
                return response

            if action_type == "fill":
                selector = str(plan.get("selector") or "")
                value = plan.get("value", "")
                if not selector:
                    return {"success": False, "error": "fill plan missing selector", "output": ""}
                await page.locator(selector).first.fill(str(value))
                return {
                    "success": True,
                    "output": value,
                    "effect": {"type": "fill", "action_performed": True},
                }

            if action_type == "extract_snapshot":
                return _execute_extract_snapshot_plan(plan)

            code = str(plan.get("code") or "")
            if "async def run(page, results)" not in code:
                return {"success": False, "error": "plan missing async def run(page, results)", "output": ""}
            namespace: Dict[str, Any] = {}
            _cache_generated_code_for_traceback(code)
            exec(compile(code, _GENERATED_CODE_FILENAME, "exec"), namespace, namespace)
            runner = namespace.get("run")
            if not callable(runner):
                return {"success": False, "error": "No run(page, results) function defined", "output": ""}
            navigation_history: List[str] = []
            original_goto = getattr(page, "goto", None)
            goto_wrapped = False
            download_capture = _DownloadEventCapture(page)

            if callable(original_goto):
                async def tracked_goto(url: str, *args: Any, **kwargs: Any) -> Any:
                    response = original_goto(url, *args, **kwargs)
                    if inspect.isawaitable(response):
                        response = await response
                    navigation_history.append(str(getattr(page, "url", "") or url or ""))
                    return response

                try:
                    setattr(page, "goto", tracked_goto)
                    goto_wrapped = True
                except Exception:
                    goto_wrapped = False

            download_capture.start()

            try:
                output = runner(page, runtime_results)
                if inspect.isawaitable(output):
                    output = await output
                await download_capture.drain(should_wait=_should_drain_download_events(plan, code))
            finally:
                download_capture.close()
                if goto_wrapped:
                    try:
                        setattr(page, "goto", original_goto)
                    except Exception:
                        pass

            response = {"success": True, "error": None, "output": output}
            if navigation_history:
                response["navigation_history"] = navigation_history
            download_signal = download_capture.signal()
            if download_signal:
                response["signals"] = {"download": download_signal}
                response["effect"] = {"type": "download", "action_performed": True}
            return response
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "traceback": _format_exception_for_repair(exc),
                "output": "",
            }


def _execute_extract_snapshot_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    fields = _snapshot_plan_fields(plan)
    if not fields:
        return {"success": False, "error": "extract_snapshot plan missing fields", "output": ""}

    output: Dict[str, Any] = {}
    selected_fields: List[Dict[str, Any]] = []
    include_hidden = _normalize_bool(plan.get("include_hidden"))
    for field in fields:
        label = str(field.get("label") or "").strip()
        if not label:
            continue
        visible = bool(field.get("visible", True))
        value = field.get("value")
        if not visible and not include_hidden:
            continue
        output[label] = value
        selected_fields.append(
            {
                "label": label,
                "value": value,
                "data_prop": str(field.get("data_prop") or "").strip(),
                "visible": visible,
                "value_kind": str(field.get("value_kind") or "").strip(),
                "required": bool(field.get("required")),
            }
        )

    empty_required_label = _empty_required_snapshot_field_label(plan)
    if empty_required_label:
        return {
            "success": False,
            "error": "extract_snapshot required field has empty value",
            "output": "",
            "diagnostics": {"field": empty_required_label},
        }

    if _requires_non_empty_extract_snapshot_output(plan) and not _extract_snapshot_plan_has_visible_value(plan):
        return {
            "success": False,
            "error": "extract_snapshot plan produced no visible non-empty fields",
            "output": "",
        }

    return {
        "success": True,
        "error": None,
        "output": output,
        "signals": {
            "extract_snapshot": {
                "source": str(plan.get("source") or "").strip(),
                "section_title": str(plan.get("section_title") or "").strip(),
                "frame_path": _snapshot_plan_frame_path(plan),
                "fields": selected_fields,
            }
        },
    }


def _snapshot_plan_frame_path(plan: Dict[str, Any]) -> List[str]:
    frame_path = plan.get("frame_path")
    if isinstance(frame_path, list):
        return [str(item) for item in frame_path if str(item or "").strip()]
    extraction = plan.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("frame_path"), list):
        return [str(item) for item in extraction["frame_path"] if str(item or "").strip()]
    return []


def _snapshot_plan_fields(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = plan.get("fields")
    if isinstance(fields, list):
        return [dict(field) for field in fields if isinstance(field, dict)]
    extraction = plan.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("fields"), list):
        return [dict(field) for field in extraction["fields"] if isinstance(field, dict)]
    return []


def _extract_snapshot_plan_has_visible_value(plan: Dict[str, Any]) -> bool:
    include_hidden = _normalize_bool(plan.get("include_hidden"))
    include_empty = _normalize_bool(plan.get("include_empty"))
    for field in _snapshot_plan_fields(plan):
        if not str(field.get("label") or "").strip():
            continue
        if not bool(field.get("visible", True)) and not include_hidden:
            continue
        if field.get("value") == "" and not include_empty:
            continue
        return True
    return False


def _empty_required_snapshot_field_label(plan: Dict[str, Any]) -> str:
    include_hidden = _normalize_bool(plan.get("include_hidden"))
    for field in _snapshot_plan_fields(plan):
        label = str(field.get("label") or "").strip()
        if not label or not _normalize_bool(field.get("required")):
            continue
        if not bool(field.get("visible", True)) and not include_hidden:
            continue
        value = field.get("value")
        if value in (None, ""):
            return label
        if isinstance(value, (list, dict)) and not value:
            return label
    return ""


def _requires_non_empty_extract_snapshot_output(plan: Dict[str, Any]) -> bool:
    if plan.get("_allow_empty_output_explicit") is False:
        return False
    if "allow_empty_output" not in plan:
        return False
    return not _normalize_bool(plan.get("allow_empty_output"))


def _selected_region_extract_plan_validation_error(plan: Dict[str, Any]) -> str:
    if str(plan.get("action_type") or "").strip() != "extract_snapshot":
        return ""
    fields = _snapshot_plan_fields(plan)
    if not fields:
        return "extract_snapshot plan missing fields"
    if _empty_required_snapshot_field_label(plan):
        return "extract_snapshot required field has empty value"
    if _requires_non_empty_extract_snapshot_output(plan) and not _extract_snapshot_plan_has_visible_value(plan):
        return "extract_snapshot plan produced no visible non-empty fields"
    return ""


def _build_region_plan_validation_payload(
    payload: Dict[str, Any],
    failed_plan: Dict[str, Any],
    error: str,
) -> Dict[str, Any]:
    return {
        **payload,
        "plan_validation": {
            "error": error,
            "failed_plan": _safe_jsonable(failed_plan),
            "snapshot": _safe_jsonable(payload.get("snapshot")),
            "requirement": (
                "The failed selected-region plan was not executable. "
                "If using extract_snapshot, return a fields array with labels copied from "
                "snapshot.detail_views or selected-region evidence. Empty values are allowed "
                "unless the field is required or the plan explicitly disallows empty output. Otherwise return run_python "
                "using selected-region locator evidence."
            ),
        },
    }


def _trace_replay_code_from_plan(plan: Dict[str, Any]) -> str:
    action_type = str(plan.get("action_type") or "").strip().lower()
    if action_type == "extract_snapshot":
        return _extract_snapshot_preview_code(plan)

    code = str(plan.get("code") or "")
    if code.strip():
        return code

    if action_type == "click":
        selector = str(plan.get("selector") or "").strip()
        if selector:
            return (
                "async def run(page, results):\n"
                f"    await page.locator({selector!r}).first.click()\n"
                "    return {'action_performed': True}"
            )

    if action_type == "fill":
        selector = str(plan.get("selector") or "").strip()
        value = str(plan.get("value") or "")
        if selector:
            return (
                "async def run(page, results):\n"
                f"    await page.locator({selector!r}).first.fill({value!r})\n"
                "    return {'action_performed': True, 'action_type': 'fill', 'filled_value': "
                f"{value!r}" + "}"
            )

    if action_type == "goto":
        url = str(plan.get("url") or "").strip()
        if url:
            return (
                "async def run(page, results):\n"
                f"    await page.goto({url!r}, wait_until='domcontentloaded')\n"
                "    return {'action_performed': True}"
            )

    return ""


def _extract_snapshot_preview_code(plan: Dict[str, Any]) -> str:
    fields = _snapshot_plan_fields(plan)
    labels = [str(field.get("label") or "").strip() for field in fields if str(field.get("label") or "").strip()]
    lines = [
        "# extract_snapshot: values were read from the current compact snapshot during recording",
        "# final skill compilation will generate Playwright extraction code from this evidence",
    ]
    source = str(plan.get("source") or "").strip()
    section_title = str(plan.get("section_title") or "").strip()
    if source:
        lines.append(f"# source: {source}")
    if section_title:
        lines.append(f"# section: {section_title}")
    for label in labels[:20]:
        lines.append(f"# field: {label}")
    return "\n".join(lines)


def _extract_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        if content:
            return content
        reasoning = getattr(response, "additional_kwargs", {}).get("reasoning_content") if hasattr(response, "additional_kwargs") else ""
        return str(reasoning or "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item.get("thinking") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _parse_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    original_raw = raw
    decoder = json.JSONDecoder()
    candidates: List[str] = [
        match.group(1)
        for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    ]
    candidates.extend(raw[index:] for index, char in enumerate(raw) if char == "{")
    if not candidates and raw:
        candidates.append(raw)

    last_json_error: Optional[json.JSONDecodeError] = None
    last_contract_error: Optional[ValueError] = None
    for candidate in candidates:
        try:
            parsed, _end = decoder.raw_decode(candidate)
        except json.JSONDecodeError as exc:
            last_json_error = exc
            continue
        try:
            return _coerce_recording_plan(parsed)
        except ValueError as exc:
            last_contract_error = exc
            continue

    if last_contract_error is not None:
        raise RecordingPlannerContractError(
            str(last_contract_error),
            raw_output=original_raw,
            cause=last_contract_error,
        ) from last_contract_error
    if last_json_error is not None:
        raise RecordingPlannerContractError(
            f"Recording planner returned invalid JSON: {last_json_error.msg}",
            raw_output=original_raw,
            cause=last_json_error,
        ) from last_json_error
    raise RecordingPlannerContractError(
        "Recording planner did not return a JSON object",
        raw_output=original_raw,
    )


def _coerce_recording_plan(parsed: Any) -> Dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ValueError("Recording planner must return a JSON object")
    parsed.setdefault("action_type", "run_python")
    parsed["expected_effect"] = _normalize_expected_effect(parsed.get("expected_effect"))
    parsed["_allow_empty_output_explicit"] = "allow_empty_output" in parsed
    parsed["allow_empty_output"] = _normalize_bool(parsed.get("allow_empty_output"))
    if parsed.get("action_type") == "run_python":
        code = str(parsed.get("code") or "")
        if "async def run(page, results)" not in code:
            wrapped_code = _wrap_top_level_run_python_code(code)
            if wrapped_code:
                parsed["code"] = wrapped_code
            else:
                raise ValueError("Recording planner must return Python code defining async def run(page, results)")
    return parsed


def _wrap_top_level_run_python_code(code: str) -> Optional[str]:
    source = str(code or "").strip()
    if not _looks_like_top_level_python(source):
        return None
    body = "\n".join(("    " + line) if line.strip() else "" for line in source.splitlines())
    wrapped = "async def run(page, results):\n" + (body or "    return None")
    try:
        compile(wrapped, _GENERATED_CODE_FILENAME, "exec")
    except SyntaxError:
        return None
    return wrapped


def _looks_like_top_level_python(source: str) -> bool:
    if not source or "async def run(page, results)" in source:
        return False
    python_signals = (
        "page.",
        "await ",
        "results",
    )
    return any(signal in source for signal in python_signals)


def _planner_contract_diagnostic(
    exc: BaseException,
    *,
    stage: str,
    model_config: Optional[Dict[str, Any]],
) -> RPATraceDiagnostic:
    raw_output = str(getattr(exc, "raw_output", "") or "")
    raw: Dict[str, Any] = {
        "error_type": "planner_contract",
        "stage": stage,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "model_config": _model_config_summary(model_config),
    }
    if raw_output:
        raw["planner_raw_output"] = raw_output[:4000]
        raw["planner_raw_output_truncated"] = len(raw_output) > 4000
    llm_call = getattr(exc, "llm_call", None)
    if isinstance(llm_call, dict) and llm_call:
        raw["llm_call"] = _safe_jsonable(llm_call)
    return RPATraceDiagnostic(
        source="ai",
        message=f"Recording planner failed to return a valid JSON plan: {exc}",
        raw=raw,
    )


def _model_config_summary(model_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(model_config, dict) or not model_config:
        return {}
    summary: Dict[str, Any] = {}
    for key in (
        "provider",
        "model_name",
        "base_url",
        "context_window",
        "id",
        "name",
        "requested_user_id",
        "selected_owner",
        "resolution_reason",
        "user_id",
    ):
        value = model_config.get(key)
        if value not in (None, ""):
            summary[key] = value
    return summary


def _build_planner_llm_request_summary(
    *,
    model: Any,
    messages: List[Any],
    model_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    message_summaries = []
    total_chars = 0
    include_prompt_preview = _planner_prompt_preview_enabled()
    for message in messages:
        content = str(getattr(message, "content", "") or "")
        total_chars += len(content)
        summary = {
            "type": type(message).__name__,
            "chars": len(content),
            "truncated": len(content) > 20000,
        }
        if include_prompt_preview:
            summary["preview"] = _truncate_text(content, 20000)
        message_summaries.append(summary)
    return {
        "configured_model": _model_config_summary(model_config),
        "effective_model": _effective_llm_model_summary(model),
        "message_count": len(messages),
        "total_message_chars": total_chars,
        "messages": message_summaries,
    }


def _planner_prompt_preview_enabled() -> bool:
    return str(os.getenv("RPA_LLM_DIAGNOSTIC_PROMPT_PREVIEW", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _effective_llm_model_summary(model: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    attr_map = {
        "model_name": ("model_name", "model"),
        "base_url": ("openai_api_base", "base_url"),
        "max_tokens": ("max_tokens",),
        "temperature": ("temperature",),
        "streaming": ("streaming",),
        "request_timeout": ("request_timeout", "timeout"),
        "max_retries": ("max_retries",),
        "model_kwargs": ("model_kwargs",),
        "disabled_params": ("disabled_params",),
        "profile": ("profile",),
    }
    for key, candidates in attr_map.items():
        for attr in candidates:
            value = getattr(model, attr, None)
            if value not in (None, ""):
                summary[key] = _safe_jsonable(value)
                break
    return summary


def _text_diagnostic(text: Any, *, limit: int) -> Dict[str, Any]:
    value = str(text or "")
    return {
        "chars": len(value),
        "preview": _truncate_text(value, limit),
        "truncated": len(value) > limit,
    }


def _truncate_text(text: str, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit]


def _log_planner_llm_call(llm_call: Dict[str, Any]) -> None:
    request = llm_call.get("request") if isinstance(llm_call, dict) else {}
    response = llm_call.get("response") if isinstance(llm_call, dict) else {}
    effective_model = request.get("effective_model") if isinstance(request, dict) else {}
    logger.info(
        "[RPA-LLM] planner call model=%s base_url=%s max_tokens=%s profile=%s input_chars=%s output_chars=%s",
        effective_model.get("model_name"),
        effective_model.get("base_url"),
        effective_model.get("max_tokens"),
        effective_model.get("profile"),
        request.get("total_message_chars") if isinstance(request, dict) else None,
        response.get("chars") if isinstance(response, dict) else None,
    )


def _build_table_ordinal_overlay_plan(instruction: str, snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    intent = _detect_ordinal_intent(instruction)
    if not intent:
        return None
    action = _detect_ordinal_action(instruction)
    if action not in {"click_primary", "extract_title"}:
        return None

    table = _select_table_view(snapshot, instruction)
    if not table:
        return None
    rows = list(table.get("rows") or [])
    if not rows:
        return None
    if str(intent.get("kind") or "") == "first_n":
        if action != "extract_title":
            return None
        limit = int(intent.get("limit") or 0)
        if limit <= 0:
            return None
        return _table_first_n_rows_plan(table, limit)
    index = _ordinal_index_from_intent(intent, len(rows))
    if index is None:
        return None
    column = _select_table_column(table, instruction)
    if not column:
        return None

    rows_setup = _table_rows_setup_code(table)
    column_id = str(column.get("column_id") or "")
    if column_id:
        cell_selector = f"td[data-colid={column_id!r}]"
    else:
        col_index = int(column.get("index") or 0) + 1
        cell_selector = f"td:nth-child({col_index})"

    if action == "click_primary":
        action_selector = _table_column_action_selector(table, index, column)
        if not action_selector:
            return None
        code = (
            "async def run(page, results):\n"
            f"{rows_setup}"
            f"    _row = _rows.nth({index})\n"
            f"    await _row.locator({action_selector!r}).click()\n"
            "    return {'action_performed': True}"
        )
        return {
            "description": "Click table row column action",
            "action_type": "run_python",
            "expected_effect": "none",
            "output_key": "table_row_action",
            "code": code,
            "table_ordinal_overlay": True,
        }

    code = (
        "async def run(page, results):\n"
        f"{rows_setup}"
        f"    _row = _rows.nth({index})\n"
        f"    return (await _row.locator({cell_selector!r}).inner_text()).strip()"
    )
    return {
        "description": "Extract table row column value",
        "action_type": "run_python",
        "expected_effect": "extract",
        "output_key": "table_row_value",
        "code": code,
        "table_ordinal_overlay": True,
    }


def _ordinal_index_from_intent(intent: Dict[str, int | str], row_count: int) -> Optional[int]:
    kind = str(intent.get("kind") or "")
    if kind == "last":
        return row_count - 1 if row_count else None
    if kind == "first_n":
        return None
    index = int(intent.get("index") or 0)
    return index if 0 <= index < row_count else None


def _select_table_view(snapshot: Dict[str, Any], instruction: str) -> Optional[Dict[str, Any]]:
    tables = [table for table in list(snapshot.get("table_views") or []) if table.get("rows")]
    if not tables:
        return None
    return max(tables, key=lambda table: _score_table_view_for_instruction(table, instruction))


def _score_table_view_for_instruction(table: Dict[str, Any], instruction: str) -> int:
    text = str(instruction or "").lower()
    score = len(table.get("rows") or [])
    title_parts = [str(table.get("title") or "")]
    title_parts.extend(str(item or "") for item in table.get("nearby_headings") or [])
    for title in title_parts:
        normalized = title.strip().lower()
        if not normalized:
            continue
        if normalized in text:
            score += 100
        elif all(token in text for token in normalized.split()):
            score += 40
    for column in table.get("columns") or []:
        header = str(column.get("header") or "").strip().lower()
        if header and header in text:
            score += 20
    return score


def _select_table_column(table: Dict[str, Any], instruction: str) -> Optional[Dict[str, Any]]:
    text = str(instruction or "").lower()
    columns = list(table.get("columns") or [])
    scored: List[tuple[int, Dict[str, Any]]] = []
    for column in columns:
        header = str(column.get("header") or "").lower()
        role = str(column.get("role") or "").lower()
        score = 0
        if header and header in text:
            score += 6
        if any(token and token in text for token in header.replace("_", " ").split()):
            score += 3
        if role and role in text:
            score += 3
        if role == "file_link" and any(term in text for term in ("file", "文件", "名称", "名字")):
            score += 5
        if role == "status" and any(term in text for term in ("status", "状态")):
            score += 5
        if role == "selection" and any(term in text for term in ("checkbox", "勾选", "选择")):
            score += 5
        if score:
            scored.append((score, column))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _table_row_selector(table: Dict[str, Any]) -> str:
    for row in table.get("rows") or []:
        for hint in row.get("locator_hints") or []:
            expression = str(hint.get("expression") or "")
            match = re.search(r"page\.locator\((['\"])(.*?)\1\)\.nth\(\d+\)", expression)
            if match:
                return match.group(2)
    return "tbody tr"


def _table_rows_setup_code(table: Dict[str, Any]) -> str:
    title = str(table.get("title") or "").strip()
    row_selector = _table_row_selector(table)
    if title:
        return (
            f"    _heading = page.get_by_text({title!r}, exact=True).first\n"
            "    if await _heading.count():\n"
            "        _rows = _heading.locator(\"xpath=following::table[.//tbody/tr][1]//tbody/tr\")\n"
            "    else:\n"
            f"        _rows = page.locator({row_selector!r})\n"
        )
    return f"    _rows = page.locator({row_selector!r})\n"


def _table_first_n_rows_plan(table: Dict[str, Any], limit: int) -> Optional[Dict[str, Any]]:
    columns = []
    for column in table.get("columns") or []:
        header = str(column.get("header") or "").strip()
        if not header:
            continue
        column_id = str(column.get("column_id") or "").strip()
        if column_id:
            selector = f"td[data-colid={column_id!r}]"
        else:
            index = int(column.get("index") or 0) + 1
            selector = f"td:nth-child({index})"
        columns.append((header, selector))
    if not columns:
        return None

    rows_setup = _table_rows_setup_code(table)
    column_specs = repr(columns)
    code = (
        "async def run(page, results):\n"
        f"{rows_setup}"
        f"    _limit = min({limit}, await _rows.count())\n"
        f"    _columns = {column_specs}\n"
        "    _records = []\n"
        "    for _i in range(_limit):\n"
        "        _row = _rows.nth(_i)\n"
        "        _record = {}\n"
        "        for _header, _selector in _columns:\n"
        "            _cell = _row.locator(_selector)\n"
        "            _record[_header] = (await _cell.inner_text()).strip() if await _cell.count() else ''\n"
        "        _records.append(_record)\n"
        "    return _records"
    )
    return {
        "description": "Extract first table rows",
        "action_type": "run_python",
        "expected_effect": "extract",
        "output_key": "table_rows",
        "code": code,
        "table_ordinal_overlay": True,
    }


def _table_column_action_selector(table: Dict[str, Any], index: int, column: Dict[str, Any]) -> str:
    column_id = str(column.get("column_id") or "")
    rows = list(table.get("rows") or [])
    if index >= len(rows):
        return ""
    for cell in rows[index].get("cells") or []:
        if column_id and str(cell.get("column_id") or "") != column_id:
            continue
        actions = list(cell.get("actions") or cell.get("row_local_actions") or [])
        for action in actions:
            locator = action.get("locator") if isinstance(action, dict) else {}
            if isinstance(locator, dict) and locator.get("scope") == "row" and locator.get("value"):
                return str(locator.get("value"))
    if column_id:
        return f"td[data-colid={column_id!r}] a, td[data-colid={column_id!r}] button"
    return ""


def _build_ordinal_overlay_plan(instruction: str, snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    intent = _detect_ordinal_intent(instruction)
    if not intent:
        return None

    action = _detect_ordinal_action(instruction)
    if not action:
        return None

    collection = _extract_repeated_candidate_collection(snapshot)
    if not collection:
        return None

    items = list(collection.get("items") or [])
    selector = str(collection.get("primary_selector") or "")
    if not selector or not items:
        return None

    kind = intent["kind"]
    index = int(intent.get("index") or 0)
    if kind == "last":
        index = len(items) - 1
    if kind in {"nth", "last"} and (index < 0 or index >= len(items)):
        return None

    if kind == "first_n":
        limit = int(intent.get("limit") or 0)
        if limit <= 0:
            return None
        return _ordinal_first_n_titles_plan(selector, limit)

    if action == "extract_title":
        return _ordinal_extract_title_plan(selector, index)

    if action == "click_secondary":
        secondary_selector = _select_secondary_action_selector(collection, instruction)
        if not secondary_selector:
            return None
        return _ordinal_click_plan(secondary_selector, index, description="Click ordinal item action")

    if action == "click_primary":
        return _ordinal_click_plan(selector, index, description="Click ordinal item")

    return None


def _detect_ordinal_intent(instruction: str) -> Optional[Dict[str, int | str]]:
    text = str(instruction or "").strip().lower()
    if not text:
        return None

    first_n = re.search(r"\bfirst\s+(\d+)\b", text) or re.search(r"前\s*([0-9一二三四五六七八九十两]+)", text)
    if first_n:
        limit = _parse_ordinal_number(first_n.group(1))
        if limit is not None:
            return {"kind": "first_n", "limit": limit}

    nth = re.search(r"\b(?:number|item|row)\s+(\d+)\b", text) or re.search(r"第\s*([0-9一二三四五六七八九十两]+)\s*(?:个|项|条|行)?", text)
    if nth:
        number = _parse_ordinal_number(nth.group(1))
        if number is not None:
            return {"kind": "nth", "index": max(number - 1, 0)}

    if any(token in text for token in ("第一个", "第一项", "第一条", "第一行", "first")):
        return {"kind": "nth", "index": 0}
    if any(token in text for token in ("第二个", "第二项", "第二条", "第二行", "second")):
        return {"kind": "nth", "index": 1}
    if any(token in text for token in ("最后一个", "最后一项", "最后一条", "最后一行", "last")):
        return {"kind": "last", "index": -1}
    return None


def _parse_ordinal_number(value: str) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text in digits:
        return digits[text]
    if text == "十":
        return 10
    if text.startswith("十") and len(text) == 2 and text[1] in digits:
        return 10 + digits[text[1]]
    if text.endswith("十") and len(text) == 2 and text[0] in digits:
        return digits[text[0]] * 10
    if "十" in text and len(text) == 3 and text[0] in digits and text[2] in digits:
        return digits[text[0]] * 10 + digits[text[2]]
    return None


def _detect_ordinal_action(instruction: str) -> str:
    text = str(instruction or "").strip().lower()
    semantic_terms = (
        "most related",
        "best match",
        "highest",
        "most relevant",
        "compare",
        "summarize",
        "summary",
        "最相关",
        "最高",
        "最多",
        "最佳",
        "比较",
        "总结",
    )
    if any(term in text for term in semantic_terms):
        return ""
    if any(term in text for term in ("download", "下载")):
        return "click_secondary"
    if any(term in text for term in ("click", "open", "visit", "go to", "点击", "打开", "进入")):
        return "click_primary"
    if any(term in text for term in ("name", "title", "text", "名称", "名字", "标题", "获取", "抓取", "提取")):
        return "extract_title"
    return ""


def _extract_repeated_candidate_collection(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for node in snapshot.get("actionable_nodes") or []:
        selector = str(node.get("collection_item_selector") or "").strip()
        count = int(node.get("collection_item_count") or 0)
        label = _node_label(node)
        if not selector or count < 2 or not label:
            continue
        if _looks_like_secondary_action_label(label):
            continue
        if str(node.get("role") or "").strip().lower() not in {"link", "button"}:
            continue
        grouped.setdefault(selector, []).append(node)

    if not grouped:
        return _extract_repeated_candidate_collection_from_frames(snapshot)

    grouped = {
        selector: nodes
        for selector, nodes in grouped.items()
        if len({_node_label(node).lower() for node in nodes}) >= 2
        and any(_looks_like_primary_item_label(_node_label(node)) for node in nodes)
    }
    if not grouped:
        return _extract_repeated_candidate_collection_from_frames(snapshot)

    selector, nodes = max(
        grouped.items(),
        key=lambda item: _score_ordinal_primary_collection(
            item[0],
            [_node_label(node) for node in item[1]],
            len(item[1]),
        ),
    )
    items = []
    for index, node in enumerate(_sort_snapshot_nodes(nodes)):
        label = _node_label(node)
        if not label:
            continue
        items.append(
            {
                "index": index,
                "title": label,
                "container_id": str(node.get("container_id") or ""),
                "primary_selector": selector,
            }
        )
    if len(items) < 2:
        return None

    secondary = _extract_secondary_action_selectors(snapshot, items)
    return {
        "kind": "repeated_candidates",
        "source": "raw_snapshot",
        "primary_selector": selector,
        "items": items,
        "secondary_selectors": secondary,
    }


def _extract_repeated_candidate_collection_from_frames(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for frame in snapshot.get("frames") or []:
        collections = list(frame.get("collections") or [])
        for collection in collections:
            if str(collection.get("kind") or "") != "repeated_items":
                continue
            selector = _collection_item_css_selector(collection)
            if not selector:
                continue
            role = str((collection.get("item_hint") or {}).get("role") or "").strip().lower()
            if role and role not in {"link", "button"}:
                continue

            items: List[Dict[str, Any]] = []
            labels: List[str] = []
            for item in collection.get("items") or []:
                label = _node_label(item)
                if not _looks_like_primary_item_label(label):
                    continue
                labels.append(label)
                items.append(
                    {
                        "index": len(items),
                        "title": label,
                        "container_id": "",
                        "primary_selector": selector,
                    }
                )

            if len(items) < 2 or len({label.lower() for label in labels}) < 2:
                continue

            candidates.append(
                {
                    "kind": "repeated_candidates",
                    "source": "raw_snapshot.frames.collections",
                    "primary_selector": selector,
                    "items": items,
                    "secondary_selectors": _extract_frame_secondary_action_selectors(collections, collection),
                    "_score": _score_ordinal_primary_collection(
                        selector,
                        labels,
                        int(collection.get("item_count") or len(items)),
                    ),
                }
            )

    if not candidates:
        return None

    selected = max(candidates, key=lambda item: item["_score"])
    selected.pop("_score", None)
    return selected


def _collection_item_css_selector(collection: Dict[str, Any]) -> str:
    item_hint = collection.get("item_hint") if isinstance(collection, dict) else {}
    locator = item_hint.get("locator") if isinstance(item_hint, dict) else {}
    if not isinstance(locator, dict) or locator.get("method") != "css":
        return ""
    return str(locator.get("value") or "").strip()


def _extract_frame_secondary_action_selectors(
    collections: List[Dict[str, Any]],
    primary_collection: Dict[str, Any],
) -> Dict[str, str]:
    primary_container = _collection_container_css_selector(primary_collection)
    if not primary_container:
        return {}

    selectors: Dict[str, str] = {}
    for collection in collections:
        if collection is primary_collection:
            continue
        if _collection_container_css_selector(collection) != primary_container:
            continue
        selector = _collection_item_css_selector(collection)
        if not selector:
            continue
        labels = [_node_label(item) for item in collection.get("items") or []]
        if sum(1 for label in labels if "download" in label.lower() or "下载" in label) >= 2:
            selectors["download"] = selector
    return selectors


def _collection_container_css_selector(collection: Dict[str, Any]) -> str:
    container_hint = collection.get("container_hint") if isinstance(collection, dict) else {}
    locator = container_hint.get("locator") if isinstance(container_hint, dict) else {}
    if not isinstance(locator, dict) or locator.get("method") != "css":
        return ""
    return str(locator.get("value") or "").strip()


def _extract_secondary_action_selectors(
    snapshot: Dict[str, Any],
    items: List[Dict[str, Any]],
) -> Dict[str, str]:
    item_container_ids = {str(item.get("container_id") or "") for item in items if item.get("container_id")}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for node in snapshot.get("actionable_nodes") or []:
        container_id = str(node.get("container_id") or "")
        if container_id not in item_container_ids:
            continue
        label = _node_label(node).lower()
        selector = str(node.get("collection_item_selector") or "").strip()
        if not selector:
            continue
        if "download" in label or "下载" in label:
            grouped.setdefault("download", []).append(node)

    selectors: Dict[str, str] = {}
    for action, nodes in grouped.items():
        by_selector: Dict[str, int] = {}
        for node in nodes:
            selector = str(node.get("collection_item_selector") or "").strip()
            by_selector[selector] = by_selector.get(selector, 0) + 1
        selector, count = max(by_selector.items(), key=lambda item: item[1])
        if count >= min(2, len(items)):
            selectors[action] = selector
    return selectors


def _select_secondary_action_selector(collection: Dict[str, Any], instruction: str) -> str:
    text = str(instruction or "").lower()
    secondary = collection.get("secondary_selectors") if isinstance(collection, dict) else {}
    if ("download" in text or "下载" in text) and isinstance(secondary, dict):
        return str(secondary.get("download") or "")
    return ""


def _ordinal_extract_title_plan(selector: str, index: int) -> Dict[str, Any]:
    code = (
        "async def run(page, results):\n"
        f"    _item = page.locator({selector!r}).nth({index})\n"
        "    return (await _item.inner_text()).strip()"
    )
    return {
        "description": "Extract ordinal item title",
        "action_type": "run_python",
        "expected_effect": "extract",
        "output_key": "ordinal_item_name",
        "code": code,
        "ordinal_overlay": True,
    }


def _ordinal_first_n_titles_plan(selector: str, limit: int) -> Dict[str, Any]:
    code = (
        "async def run(page, results):\n"
        f"    _items = page.locator({selector!r})\n"
        f"    _limit = min({limit}, await _items.count())\n"
        "    _result = []\n"
        "    for _index in range(_limit):\n"
        "        _result.append((await _items.nth(_index).inner_text()).strip())\n"
        "    return _result"
    )
    return {
        "description": "Extract first ordinal item titles",
        "action_type": "run_python",
        "expected_effect": "extract",
        "output_key": "ordinal_item_names",
        "code": code,
        "ordinal_overlay": True,
    }


def _ordinal_click_plan(selector: str, index: int, *, description: str) -> Dict[str, Any]:
    code = (
        "async def run(page, results):\n"
        f"    await page.locator({selector!r}).nth({index}).click()\n"
        "    return {'action_performed': True}"
    )
    return {
        "description": description,
        "action_type": "run_python",
        "expected_effect": "none",
        "output_key": "ordinal_item_action",
        "code": code,
        "ordinal_overlay": True,
    }


def _node_label(node: Dict[str, Any]) -> str:
    return " ".join(str(node.get(key) or "").strip() for key in ("name", "text") if str(node.get(key) or "").strip()).strip()


def _looks_like_primary_item_label(label: str) -> bool:
    text = str(label or "").strip()
    if not text or _looks_like_secondary_action_label(text):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", text))


def _score_ordinal_primary_collection(selector: str, labels: List[str], item_count: int) -> tuple[int, int, int, int, int, int]:
    meaningful_labels = [label for label in labels if _looks_like_primary_item_label(label)]
    distinct_count = len({label.lower() for label in meaningful_labels})
    heading_selector = 1 if re.search(r"(^|\s)h[1-6](\.|\s|$)", selector) else 0
    slash_pair_count = sum(1 for label in meaningful_labels if re.search(r"\S+\s*/\s*\S+", label))
    average_length = int(sum(len(label) for label in meaningful_labels) / max(len(meaningful_labels), 1))
    return (
        heading_selector,
        slash_pair_count,
        min(int(item_count or 0), 25),
        distinct_count,
        min(average_length, 80),
        len(meaningful_labels),
    )


def _sort_snapshot_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        nodes,
        key=lambda node: (
            int((node.get("bbox") or {}).get("y", 0) or 0),
            int((node.get("bbox") or {}).get("x", 0) or 0),
            int(node.get("index") or 0),
            str(node.get("node_id") or ""),
        ),
    )


def _looks_like_secondary_action_label(label: str) -> bool:
    text = str(label or "").strip().lower()
    if not text:
        return True
    return any(token in text for token in ("download", "下载", "star", "fork", "signed in"))


def _classify_recording_failure(error: Any) -> Dict[str, str]:
    text = str(error or "").strip()
    normalized = text.lower()
    if not normalized:
        return {"type": "unknown"}

    if (
        ("locator.fill" in normalized or "locator.click" in normalized or "fill action" in normalized or "click action" in normalized)
        and (
            "element is not visible" in normalized
            or "not visible" in normalized
            or "not editable" in normalized
            or "not enabled" in normalized
            or "visible, enabled and editable" in normalized
        )
    ):
        return {
            "type": "element_not_visible_or_not_editable",
            "hint": (
                "The locator matched or was attempted, but Playwright could not act on a visible/enabled/editable "
                "element. In repair, inspect the page after failure and choose a truly visible interactive candidate; "
                "for search goals, consider a direct encoded results URL unless the user explicitly needs UI typing."
            ),
        }

    if "strict mode violation" in normalized:
        return {
            "type": "strict_locator_violation",
            "hint": (
                "The attempted locator matched multiple elements. In repair, prefer a more scoped Playwright "
                "locator, role/name combination, or DOM scan that selects the intended element from candidates."
            ),
        }

    if (
        ("wait_for_selector" in normalized or "locator" in normalized)
        and "timeout" in normalized
        and ("waiting for" in normalized or "to be visible" in normalized)
    ):
        return {
            "type": "selector_timeout",
            "hint": (
                "The previous attempt timed out waiting for a specific selector. In repair, re-check the current "
                "page state first and consider resilient extraction through candidate link/row scanning instead "
                "of only replacing one brittle selector with another."
            ),
        }

    output_looks_empty = "output" in normalized and "empty" in normalized
    if "returned no meaningful output" in normalized or "empty record" in normalized or output_looks_empty:
        return {
            "type": "empty_extract_output",
            "hint": (
                "The browser action ran but produced empty data. In repair, verify the page is the expected page, "
                "then broaden extraction candidates or add field-level validation before accepting the result."
            ),
        }

    if "net::" in normalized or "err_connection" in normalized or ("page.goto" in normalized and "timeout" in normalized):
        return {
            "type": "navigation_timeout_or_network",
            "hint": (
                "The failure happened during navigation or page loading. In repair, keep the raw network error in "
                "mind, avoid assuming selector failure, and use the current browser state if navigation partially succeeded."
            ),
        }

    if "syntaxerror" in normalized or "indentationerror" in normalized or "nameerror" in normalized:
        return {
            "type": "syntax_or_runtime_code_error",
            "hint": (
                "The generated Python failed before completing the browser task. In repair, fix the code shape first "
                "while preserving the original user goal and current page context."
            ),
        }

    if "expected navigation effect" in normalized or "url did not change" in normalized:
        return {
            "type": "wrong_page_or_no_goal_progress",
            "hint": (
                "The code did not produce the browser-visible effect requested by the user. In repair, distinguish "
                "between extraction-only and action/navigation goals, then provide observable evidence for the intended effect."
            ),
        }

    return {"type": "unknown"}


def _known_failure_analysis(error: Any) -> Optional[Dict[str, str]]:
    analysis = _classify_recording_failure(error)
    return analysis if analysis.get("type") != "unknown" else None


def _cache_generated_code_for_traceback(code: str) -> None:
    lines = [line if line.endswith("\n") else f"{line}\n" for line in code.splitlines()]
    linecache.cache[_GENERATED_CODE_FILENAME] = (len(code), None, lines, _GENERATED_CODE_FILENAME)


def _format_exception_for_repair(exc: BaseException) -> str:
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
    return formatted or str(exc)


def _normalize_result_key(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return None
    if text[0].isdigit():
        text = f"result_{text}"
    return text[:64]


async def _page_state(page: Any) -> RPAPageState:
    title = ""
    title_fn = getattr(page, "title", None)
    if callable(title_fn):
        value = title_fn()
        if inspect.isawaitable(value):
            value = await value
        title = str(value or "")
    return RPAPageState(url=str(getattr(page, "url", "") or ""), title=title)


async def _ensure_expected_effect(
    *,
    page: Any,
    instruction: str,
    plan: Dict[str, Any],
    result: Dict[str, Any],
    before: RPAPageState,
) -> Dict[str, Any]:
    if not result.get("success"):
        return result

    expected_effect = _expected_effect(plan, instruction)
    if expected_effect in {"none", "extract"}:
        result = await _restore_extract_surface_if_needed(page=page, before=before, result=result)
        return result

    if expected_effect in {"navigate", "mixed"}:
        after = await _page_state(page)
        if _url_changed(before.url, after.url):
            effect = dict(result.get("effect") or {})
            effect.update({"type": "navigate", "url": after.url, "observed_url_change": True})
            return {**result, "effect": effect}

        target_url = _extract_target_url(result.get("output"), base_url=before.url) or _extract_target_url(
            plan,
            base_url=before.url,
        )
        if target_url:
            await page.goto(target_url, wait_until="domcontentloaded")
            wait_for_load_state = getattr(page, "wait_for_load_state", None)
            if callable(wait_for_load_state):
                wait_result = wait_for_load_state("domcontentloaded")
                if inspect.isawaitable(wait_result):
                    await wait_result
            after = await _page_state(page)
            if _url_changed(before.url, after.url):
                effect = dict(result.get("effect") or {})
                effect.update(
                    {
                        "type": "navigate",
                        "url": after.url,
                        "auto_completed": True,
                        "source": "output_url",
                    }
                )
                return {**result, "effect": effect}

        return {
            **result,
            "success": False,
            "error": "Expected navigation effect, but the page URL did not change and no target URL was available.",
        }

    if expected_effect in {"click", "fill"}:
        effect = result.get("effect")
        if isinstance(effect, dict) and effect.get("action_performed"):
            return result
        output = result.get("output")
        if isinstance(output, dict) and output.get("action_performed"):
            output_action_type = str(output.get("action_type") or output.get("type") or "").strip().lower()
            has_fill_value = expected_effect != "fill" or "filled_value" in output or "value" in output
            if has_fill_value and (not output_action_type or output_action_type == expected_effect):
                effect = dict(effect or {})
                effect.update(
                    {
                        "type": expected_effect,
                        "action_performed": True,
                        "source": "output_evidence",
                    }
                )
                return {**result, "effect": effect}
        action_type = str(plan.get("action_type") or "").strip().lower()
        if action_type == expected_effect:
            return {**result, "effect": {"type": expected_effect, "action_performed": True}}
        if expected_effect == "click" and action_type == "run_python":
            after = await _page_state(page)
            if _url_changed(before.url, after.url):
                effect = dict(result.get("effect") or {})
                effect.update(
                    {
                        "type": "click",
                        "action_performed": True,
                        "observed_url_change": True,
                        "url": after.url,
                    }
                )
                return {**result, "effect": effect}
        return {
            **result,
            "success": False,
            "error": f"Expected {expected_effect} effect, but no browser action evidence was produced.",
        }

    return result


def _expected_effect(plan: Dict[str, Any], instruction: str) -> str:
    explicit = _normalize_expected_effect(plan.get("expected_effect") or plan.get("effect"))
    if explicit != "extract":
        return explicit

    action_type = str(plan.get("action_type") or "").strip().lower()
    if action_type == "goto":
        return "navigate"
    if action_type in {"click", "fill"}:
        return action_type

    text = str(instruction or "").strip().lower()
    if _contains_any(text, ("打开", "进入", "跳转", "访问", "open", "go to", "goto", "navigate", "visit")):
        return "navigate"
    if _contains_any(text, ("点击", "click", "press")):
        return "click"
    if _contains_any(text, ("填写", "填入", "输入", "fill", "type into", "enter ")):
        return "fill"
    return explicit


def _normalize_expected_effect(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"extract", "navigate", "click", "fill", "mixed", "none"} else "extract"


def _should_drain_download_events(plan: Dict[str, Any], code: str) -> bool:
    action_type = str(plan.get("action_type") or "").strip().lower()
    if action_type in {"click", "press"}:
        return True
    if action_type != "run_python":
        return False
    return any(
        token in code
        for token in (
            ".click(",
            ".press(",
            ".check(",
            ".uncheck(",
            ".select_option(",
            ".set_input_files(",
        )
    )


def _merge_runtime_ai_signal(signals: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    if not _normalize_bool(plan.get("preserve_runtime_ai")):
        return signals
    runtime_ai = signals.get("runtime_ai") if isinstance(signals.get("runtime_ai"), dict) else {}
    reason = str(plan.get("semantic_intent") or runtime_ai.get("reason") or "semantic_candidate_selection").strip()
    signals["runtime_ai"] = {
        **runtime_ai,
        "preserve": True,
        "reason": reason or "semantic_candidate_selection",
    }
    return signals


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


async def _restore_extract_surface_if_needed(
    *,
    page: Any,
    before: RPAPageState,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    after = await _page_state(page)
    if not before.url or not _url_changed(before.url, after.url):
        return result
    if not _is_machine_endpoint_url(after.url, before_url=before.url):
        return result

    restore_url = _last_user_facing_url(result.get("navigation_history"), before_url=before.url) or before.url
    await page.goto(restore_url, wait_until="domcontentloaded")
    await _wait_for_load_state(page, "domcontentloaded")
    restored = await _page_state(page)
    effect = dict(result.get("effect") or {})
    effect.update(
        {
            "type": "extract",
            "restored_after_transient_endpoint": True,
            "transient_url": after.url,
            "url": restored.url,
        }
    )
    return {**result, "effect": effect}


async def _wait_for_load_state(page: Any, state: str) -> None:
    wait_for_load_state = getattr(page, "wait_for_load_state", None)
    if not callable(wait_for_load_state):
        return
    wait_result = wait_for_load_state(state)
    if inspect.isawaitable(wait_result):
        await wait_result


def _url_changed(before_url: str, after_url: str) -> bool:
    before = str(before_url or "").rstrip("/")
    after = str(after_url or "").rstrip("/")
    return bool(after) and before != after


def _is_machine_endpoint_url(url: str, *, before_url: str = "") -> bool:
    parsed = urlparse(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host.startswith("api.") or ".api." in host:
        return True
    if "/api/" in path or path.startswith("/api/"):
        return True
    if path.endswith((".json", ".xml")):
        return True

    before_host = urlparse(str(before_url or "")).netloc.lower()
    return bool(before_host and host != before_host and host.startswith(("raw.", "gist.")))


def _last_user_facing_url(history: Any, *, before_url: str = "") -> str:
    if not isinstance(history, list):
        return ""
    for item in reversed(history):
        url = str(item or "").strip()
        if url and not _is_machine_endpoint_url(url, before_url=before_url):
            return url
    return ""


def _extract_target_url(value: Any, *, base_url: str = "") -> str:
    if isinstance(value, str):
        return _normalize_target_url(value, base_url=base_url)
    if isinstance(value, dict):
        for key in ("target_url", "url", "href", "repo_url", "value"):
            target_url = _extract_target_url(value.get(key), base_url=base_url)
            if target_url:
                return target_url
        output_url = _extract_target_url(value.get("output"), base_url=base_url)
        if output_url:
            return output_url
    return ""


def _normalize_target_url(value: str, *, base_url: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("/") and base_url:
        return urljoin(base_url, text)
    return ""


def _extract_primary_locator_from_code(code: str) -> Dict[str, Any]:
    match = re.search(r"page\.locator\((?P<quote>['\"])(?P<selector>.+?)(?P=quote)\)", code or "")
    if not match:
        return {}
    return {"method": "css", "value": match.group("selector")}


def _extract_unstable_signals(locator: Dict[str, Any]) -> List[Dict[str, Any]]:
    if locator.get("method") != "css":
        return []
    selector = str(locator.get("value") or "")
    signals: List[Dict[str, Any]] = []
    patterns = {
        "data-testid": re.compile(r"""\[\s*data-testid\s*=\s*["']([^"']+)["']\s*\]"""),
        "data-test": re.compile(r"""\[\s*data-test\s*=\s*["']([^"']+)["']\s*\]"""),
        "id": re.compile(r"""#([A-Za-z0-9_-]+)"""),
        "class": re.compile(r"""\.([A-Za-z0-9_-]+)"""),
    }
    for attribute, pattern in patterns.items():
        for match in pattern.finditer(selector):
            value = match.group(1)
            if _RANDOM_LIKE_ATTR_RE.search(value):
                signals.append({"attribute": attribute, "value": value})
    return signals


def _build_anchor_candidate(anchor_title: str, role: str, name: str) -> RPALocatorStabilityCandidate:
    return RPALocatorStabilityCandidate(
        locator={
            "method": "nested",
            "parent": {"method": "text", "value": anchor_title},
            "child": {"method": "role", "role": role, "name": name},
        },
        source="snapshot_anchor_scope",
        confidence="high",
    )


def _build_locator_stability_metadata(
    plan: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Optional[RPALocatorStabilityMetadata]:
    primary_locator = _extract_primary_locator_from_code(str(plan.get("code") or ""))
    if not primary_locator:
        return None

    unstable_signals = _extract_unstable_signals(primary_locator)
    if not unstable_signals:
        return None

    fallback_metadata = RPALocatorStabilityMetadata(
        primary_locator=primary_locator,
        unstable_signals=unstable_signals,
    )

    for node in snapshot.get("actionable_nodes") or []:
        locator = node.get("locator") or {}
        role = str(node.get("role") or locator.get("role") or "").strip()
        name = str(node.get("name") or locator.get("name") or node.get("text") or "").strip()
        if not role or not name:
            continue
        anchor = str((node.get("container") or {}).get("title") or "").strip()
        alternate_locators = [
            RPALocatorStabilityCandidate(
                locator={"method": "role", "role": role, "name": name},
                source="snapshot_actionable_node",
                confidence="high",
            )
        ]
        if anchor:
            alternate_locators.append(_build_anchor_candidate(anchor, role, name))
        return RPALocatorStabilityMetadata(
            primary_locator=primary_locator,
            stable_self_signals={"role": role, "name": name},
            stable_anchor_signals={"title": anchor} if anchor else {},
            unstable_signals=unstable_signals,
            alternate_locators=alternate_locators,
        )
    return fallback_metadata


async def _safe_page_snapshot(page: Any, region_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        if region_scope:
            try:
                return await build_page_snapshot(page, build_frame_path, region_scope=region_scope)
            except TypeError as exc:
                if "region_scope" not in str(exc):
                    raise
                payload = await build_page_snapshot(page, build_frame_path)
                if isinstance(payload, dict):
                    payload.setdefault("region_scope", dict(region_scope))
                return payload
        return await build_page_snapshot(page, build_frame_path)
    except Exception:
        payload = {"url": getattr(page, "url", ""), "title": "", "frames": []}
        if region_scope:
            payload["region_scope"] = dict(region_scope)
        return payload


async def _capture_page_snapshot(page: Any, *, region_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not region_scope:
        return await _safe_page_snapshot(page)
    try:
        return await _safe_page_snapshot(page, region_scope=region_scope)
    except TypeError as exc:
        if "region_scope" not in str(exc):
            raise
        snapshot = await _safe_page_snapshot(page)
        if isinstance(snapshot, dict):
            snapshot.setdefault("region_scope", dict(region_scope))
        return snapshot


def _compact_snapshot_for_runtime(
    snapshot: Dict[str, Any],
    instruction: str,
    *,
    region_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not region_scope:
        return _compact_snapshot(snapshot, instruction)
    try:
        compact = _compact_snapshot(snapshot, instruction, region_scope=region_scope)
        if isinstance(compact, dict):
            _merge_compact_region_scope(compact, region_scope)
        return compact
    except TypeError as exc:
        if "region_scope" not in str(exc):
            raise
        compact = _compact_snapshot(snapshot, instruction)
        if isinstance(compact, dict):
            compact.setdefault("region_scope", dict(region_scope))
            _merge_compact_region_scope(compact, region_scope)
        return compact


def _merge_compact_region_scope(compact_snapshot: Dict[str, Any], region_scope: Dict[str, Any]) -> None:
    snapshot_scope = compact_snapshot.get("region_scope")
    if not isinstance(snapshot_scope, dict):
        compact_snapshot["region_scope"] = dict(region_scope)
        return
    for key in ("region_id", "mode", "frame_path", "frame_rect", "acquisition"):
        value = region_scope.get(key)
        if value not in (None, "", [], {}) and key not in snapshot_scope:
            snapshot_scope[key] = value


def _region_scope_from_context(region_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    context = _object_dict(region_context)
    evidence = _object_dict(context.get("evidence"))
    if not context and not evidence:
        return {}
    rect = _safe_jsonable(evidence.get("rect") or {})
    if not isinstance(rect, dict):
        rect = {}
    return {
        "region_id": str(context.get("region_id") or ""),
        "session_id": str(context.get("session_id") or ""),
        "tab_id": str(context.get("tab_id") or ""),
        "page_url": str(context.get("page_url") or evidence.get("url") or ""),
        "page_title": str(context.get("page_title") or evidence.get("title") or ""),
        "viewport_rect": dict(rect),
        "frame_path": _compact_list(evidence.get("frame_path")),
        "frame_rect": dict(rect),
        "acquisition": str(context.get("acquisition") or evidence.get("acquisition") or ""),
        "warnings": _compact_list(evidence.get("warnings")),
    }


def _compact_region_context(region_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    context = _object_dict(region_context)
    evidence = _object_dict(context.get("evidence"))
    if not evidence:
        evidence = {
            key: context.get(key)
            for key in (
                "inferred_kind",
                "acquisition",
                "frame_path",
                "rect",
                "local_text",
                "dominant_container",
                "locator_candidates",
                "scope_candidates",
                "intersecting_elements",
                "table_summary",
                "list_summary",
                "action_summary",
                "warnings",
            )
            if key in context
        }
    if not context and not evidence:
        return {}

    compact: Dict[str, Any] = {}
    _set_if_present(compact, "region_id", context.get("region_id"))
    _set_if_present(compact, "tab_id", context.get("tab_id"))
    _set_if_present(compact, "page_url", context.get("page_url") or evidence.get("url"))
    _set_if_present(compact, "page_title", context.get("page_title") or evidence.get("title"))
    _set_if_present(compact, "inferred_kind", evidence.get("inferred_kind"))
    _set_if_present(compact, "acquisition", context.get("acquisition") or evidence.get("acquisition"))
    _set_if_present(compact, "frame_path", _compact_list(evidence.get("frame_path")))
    _set_if_present(compact, "rect", evidence.get("rect"))
    _set_if_present(compact, "local_text", _compact_list(evidence.get("local_text"), limit=20))
    _set_if_present(compact, "dominant_container", evidence.get("dominant_container"))
    _set_if_present(compact, "locator_candidates", _compact_list(evidence.get("locator_candidates"), limit=10))
    _set_if_present(compact, "scope_candidates", _compact_list(evidence.get("scope_candidates"), limit=10))
    _set_if_present(compact, "intersecting_elements", _compact_list(evidence.get("intersecting_elements"), limit=20))
    _set_if_present(compact, "table_summary", evidence.get("table_summary"))
    _set_if_present(compact, "list_summary", evidence.get("list_summary"))
    _set_if_present(compact, "action_summary", evidence.get("action_summary"))
    _set_if_present(compact, "warnings", _compact_list(evidence.get("warnings")))
    return _safe_jsonable(compact) if compact else {}


def _selected_region_snapshot(
    compact_snapshot: Dict[str, Any],
    page_state: RPAPageState,
    region_context: Dict[str, Any],
) -> Dict[str, Any]:
    snapshot = {
        "mode": "selected_region_snapshot",
        "url": str(compact_snapshot.get("url") or page_state.url or ""),
        "title": str(compact_snapshot.get("title") or page_state.title or ""),
        "selected_region": region_context,
        "scope_note": (
            "The user selected this page region for the current command. "
            "Plan extraction or action targeting from selected_region evidence first."
        ),
    }
    detail_views = _selected_region_detail_views(region_context)
    if detail_views:
        snapshot["detail_views"] = detail_views
    return snapshot


def _selected_region_detail_views(region_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    local_text = [str(item or "").strip() for item in list(region_context.get("local_text") or [])]
    local_text = [item for item in local_text if item]
    if not local_text:
        return []
    fields: List[Dict[str, Any]] = []
    if len(local_text) > 1:
        fields.append(
            {
                "label": "selected_region_text",
                "value": "\n".join(local_text),
                "visible": True,
                "value_kind": "text",
            }
        )
    fields.extend(
        {
            "label": f"selected_region_text_{index}",
            "value": text,
            "visible": True,
            "value_kind": "text",
        }
        for index, text in enumerate(local_text, start=1)
    )
    return [
        {
            "source": "selected_region.local_text",
            "section_title": "Selected region text",
            "fields": fields,
        }
    ]


def _build_recording_planner_payload(
    *,
    instruction: str,
    page_state: RPAPageState,
    compact_snapshot: Dict[str, Any],
    runtime_results: Dict[str, Any],
    compact_region_context: Dict[str, Any],
) -> Dict[str, Any]:
    if compact_region_context:
        return {
            "instruction": instruction,
            "page": {
                "url": page_state.url,
                "title": page_state.title,
            },
            "context_scope": "selected_region",
            "snapshot": _selected_region_snapshot(compact_snapshot, page_state, compact_region_context),
            "region_context": compact_region_context,
            "runtime_results": runtime_results,
        }
    return {
        "instruction": instruction,
        "page": page_state.model_dump(mode="json"),
        "context_scope": "full_page",
        "snapshot": compact_snapshot,
        "runtime_results": runtime_results,
    }


def _raw_region_evidence(region_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    context = _object_dict(region_context)
    evidence = _object_dict(context.get("evidence"))
    return _safe_jsonable(evidence) if evidence else {}


def _region_selection_signal(region_context: Dict[str, Any]) -> Dict[str, Any]:
    signal: Dict[str, Any] = {}
    _set_if_present(signal, "region_id", region_context.get("region_id"))
    _set_if_present(signal, "inferred_kind", region_context.get("inferred_kind"))
    _set_if_present(signal, "rect", region_context.get("rect"))
    _set_if_present(signal, "frame_path", region_context.get("frame_path"))
    _set_if_present(signal, "local_text_preview", region_context.get("local_text"))
    _set_if_present(signal, "table", region_context.get("table_summary"))
    _set_if_present(signal, "list", region_context.get("list_summary"))
    _set_if_present(signal, "action", region_context.get("action_summary"))
    _set_if_present(signal, "warnings", region_context.get("warnings"))
    return signal


def _region_context_decision_signal(plan: Dict[str, Any], region_context: Dict[str, Any]) -> Dict[str, Any]:
    action_type = str(plan.get("action_type") or "").strip()
    output_key = _normalize_result_key(plan.get("output_key"))
    if output_key or action_type == "data_capture":
        used_as = "extraction"
    elif action_type in {"click", "fill", "select", "press", "hover", "run_python"}:
        used_as = "action_targeting"
    else:
        used_as = "supporting_evidence"

    signal: Dict[str, Any] = {"used_as": used_as}
    _set_if_present(signal, "region_id", region_context.get("region_id"))
    _set_if_present(signal, "action_type", action_type)
    _set_if_present(signal, "output_key", output_key)
    return signal


def _region_text_extract_signal(
    plan: Dict[str, Any],
    compact_snapshot: Dict[str, Any],
    region_context: Dict[str, Any],
) -> Dict[str, Any]:
    action_type = str(plan.get("action_type") or "").strip()
    expected_effect = str(plan.get("expected_effect") or "").strip()
    output_key = _normalize_result_key(plan.get("output_key"))
    if action_type != "run_python" or expected_effect != "extract" or not output_key:
        return {}
    if str(compact_snapshot.get("mode") or "") != "region_scoped_snapshot":
        return {}
    if str(region_context.get("inferred_kind") or "").strip() != "text_region":
        return {}

    for region in list(compact_snapshot.get("expanded_regions") or []):
        if not isinstance(region, dict):
            continue
        evidence = region.get("evidence") if isinstance(region.get("evidence"), dict) else {}
        anchor = evidence.get("section_anchor") if isinstance(evidence.get("section_anchor"), dict) else {}
        body_texts = [item for item in list(evidence.get("selected_body_texts") or []) if isinstance(item, dict)]
        if not anchor or not body_texts:
            continue
        relation = str(anchor.get("relation") or "").strip()
        if relation not in {"inside_heading", "preceding_heading"}:
            continue
        strategy = str(anchor.get("text_strategy") or "bounded_section_text").strip()
        if strategy != "bounded_section_text":
            continue
        heading_text = str(anchor.get("text") or "").strip()
        heading_locator = anchor.get("locator") if isinstance(anchor.get("locator"), dict) else {}
        if not heading_text or not heading_locator:
            continue
        observed_body_values = [
            str(item.get("text") or "").strip()
            for item in body_texts
            if str(item.get("text") or "").strip()
        ]
        if not locator_is_replay_safe_for_region_extract(heading_locator, observed_values=observed_body_values):
            continue
        return {
            "source": "region_scoped_snapshot",
            "intent": "anchored_region_extract",
            "kind": "heading_scoped_text",
            "section_title": heading_text,
            "heading_locator": dict(heading_locator),
            "heading_relation": relation,
            "text_strategy": "bounded_section_text",
            "output_key": output_key,
            "frame_path": list(region.get("frame_path") or []),
        }
    return {}


def _selected_region_text_extract_signal(
    plan: Dict[str, Any],
    result: Dict[str, Any],
    region_context: Dict[str, Any],
) -> Dict[str, Any]:
    action_type = str(plan.get("action_type") or "").strip()
    expected_effect = str(plan.get("expected_effect") or "").strip()
    output_key = _normalize_result_key(plan.get("output_key"))
    if action_type not in {"run_python", "extract_snapshot", ""} or not output_key:
        return {}
    if expected_effect and expected_effect != "extract":
        return {}
    if str(region_context.get("inferred_kind") or "").strip() != "text_region":
        return {}
    if _selected_region_has_structured_region_evidence(region_context):
        return {}

    label = _selected_region_text_label(plan, result)
    observed_values = _selected_region_observed_text_values(plan, result, region_context)
    locator, observed_text = _selected_region_text_target_locator(region_context, observed_values)
    if not locator or not observed_text:
        return {}

    signal: Dict[str, Any] = {
        "source": "region_context",
        "intent": "single_value_extract",
        "output_key": output_key,
        "locator": locator,
        "frame_path": list(region_context.get("frame_path") or []),
        "observed_text": observed_text,
    }
    _set_if_present(signal, "region_id", region_context.get("region_id"))
    _set_if_present(signal, "label", label)
    return signal


def _selected_region_has_structured_region_evidence(region_context: Dict[str, Any]) -> bool:
    table_summary = region_context.get("table_summary") if isinstance(region_context.get("table_summary"), dict) else {}
    list_summary = region_context.get("list_summary") if isinstance(region_context.get("list_summary"), dict) else {}
    action_summary = region_context.get("action_summary") if isinstance(region_context.get("action_summary"), dict) else {}
    if table_summary.get("locator_candidates") or table_summary.get("headers") or table_summary.get("sample_rows"):
        return True
    if list_summary.get("item_selector") or list_summary.get("container_locator_candidates"):
        return True
    controls = action_summary.get("controls")
    return isinstance(controls, list) and bool(controls)


def _selected_region_text_label(plan: Dict[str, Any], result: Dict[str, Any]) -> str:
    fields = _snapshot_plan_fields(plan)
    labels = [str(field.get("label") or "").strip() for field in fields if str(field.get("label") or "").strip()]
    if len(labels) == 1:
        return labels[0]
    output = result.get("output")
    if isinstance(output, dict) and len(output) == 1:
        return str(next(iter(output.keys())) or "").strip()
    return ""


def _selected_region_text_target_locator(
    region_context: Dict[str, Any],
    observed_values: set[str],
) -> tuple[Dict[str, Any], str]:
    local_texts = [
        str(item or "").strip()
        for item in list(region_context.get("local_text") or [])
        if str(item or "").strip()
    ]
    if not local_texts:
        return {}, ""
    min_len = min(len(text) for text in local_texts)
    target_texts = {text for text in local_texts if len(text) == min_len}
    explicit_target = region_context.get("selected_text_target")
    if isinstance(explicit_target, dict):
        text = str(explicit_target.get("text") or "").strip()
        locator = _selected_region_safe_locator(explicit_target.get("locator_candidates"), observed_values)
        if text in target_texts and locator:
            return locator, text

    intersecting_elements = region_context.get("intersecting_elements")
    if not isinstance(intersecting_elements, list):
        return {}, ""
    for element in intersecting_elements:
        if not isinstance(element, dict):
            continue
        text = str(element.get("text") or element.get("name") or "").strip()
        if text not in target_texts:
            continue
        locator = _selected_region_safe_locator(element.get("locator_candidates"), observed_values)
        if locator:
            return locator, text
    return {}, ""


def _selected_region_safe_locator(candidates: Any, observed_values: set[str]) -> Dict[str, Any]:
    if not isinstance(candidates, list):
        return {}
    ordered = [candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("selected")]
    ordered.extend(candidate for candidate in candidates if isinstance(candidate, dict) and not candidate.get("selected"))
    for candidate in ordered:
        locator = normalize_locator(candidate.get("locator") if isinstance(candidate.get("locator"), dict) else candidate)
        if not locator_is_replay_safe_for_region_extract(locator, observed_values=list(observed_values)):
            continue
        return locator
    return {}


def _selected_region_observed_text_values(
    plan: Dict[str, Any],
    result: Dict[str, Any],
    region_context: Dict[str, Any],
) -> set[str]:
    values: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            values.add(value.strip())

    for item in list(region_context.get("local_text") or []):
        add(item)
    add(plan.get("section_title"))

    def walk(value: Any) -> None:
        if isinstance(value, str):
            add(value)
        elif isinstance(value, dict):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(result.get("output"))
    return values


def _object_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _compact_list(value: Any, *, limit: Optional[int] = None) -> List[Any]:
    if not isinstance(value, list):
        return []
    items = value[:limit] if limit is not None else value
    return [_safe_jsonable(item) for item in items]


def _set_if_present(target: Dict[str, Any], key: str, value: Any) -> None:
    if value in (None, "", [], {}):
        return
    target[key] = _safe_jsonable(value)


def _compact_snapshot(
    snapshot: Dict[str, Any],
    instruction: str,
    limit: int = 80,
    region_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        if region_scope is not None:
            compact_snapshot = compact_recording_snapshot(snapshot, instruction, region_scope=region_scope)
        else:
            compact_snapshot = compact_recording_snapshot(snapshot, instruction)
        if isinstance(compact_snapshot, dict):
            return compact_snapshot
    except Exception:
        pass

    compact_frames = []
    for frame in list(snapshot.get("frames") or [])[:5]:
        nodes = []
        for node in list(frame.get("elements") or [])[:limit]:
            nodes.append(
                {
                    "index": node.get("index"),
                    "tag": node.get("tag"),
                    "role": node.get("role"),
                    "name": node.get("name"),
                    "text": node.get("text"),
                    "href": node.get("href"),
                }
            )
        compact_frames.append(
            {
                "frame_hint": frame.get("frame_hint"),
                "url": frame.get("url"),
                "elements": nodes,
                "collections": frame.get("collections", [])[:10],
            }
        )
    return {
        "url": snapshot.get("url"),
        "title": snapshot.get("title"),
        "frames": compact_frames,
    }


def _write_recording_snapshot_debug(
    stage: str,
    *,
    instruction: str,
    page_state: Dict[str, Any],
    raw_snapshot: Dict[str, Any],
    compact_snapshot: Dict[str, Any],
    runtime_results: Dict[str, Any],
    debug_context: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    debug_dir = _resolve_recording_snapshot_debug_dir()
    if not debug_dir:
        return

    try:
        debug_context = dict(debug_context or {})
        target_dir = _resolve_recording_snapshot_debug_path(debug_dir, debug_context=debug_context)
        target_dir.mkdir(parents=True, exist_ok=True)
        sequence = _next_debug_sequence(target_dir)
        filename = _debug_filename(
            sequence=sequence,
            stage=stage,
            kind="snapshot",
            label=instruction,
            extension="json",
        )
        payload: Dict[str, Any] = {
            "stage": stage,
            "debug_context": debug_context,
            "instruction": instruction,
            "page": page_state,
            "raw_snapshot": raw_snapshot,
            "compact_snapshot": compact_snapshot,
            "snapshot_metrics": _build_snapshot_debug_metrics(raw_snapshot, compact_snapshot),
            "snapshot_comparison": _compare_instruction_snapshot_presence(instruction, raw_snapshot, compact_snapshot),
            "runtime_results": runtime_results,
        }
        if extra:
            payload.update(extra)
        (target_dir / filename).write_text(
            json.dumps(_safe_jsonable(payload), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("[RPA-DIAG] snapshot dump written stage=%s path=%s", stage, target_dir / filename)
    except Exception:
        logger.warning("[RPA-DIAG] snapshot dump failed stage=%s", stage, exc_info=True)
        return


def _write_recording_attempt_debug(
    stage: str,
    *,
    instruction: str,
    page_state: Dict[str, Any],
    plan: Dict[str, Any],
    execution_result: Dict[str, Any],
    failure_analysis: Optional[Dict[str, Any]] = None,
    debug_context: Optional[Dict[str, Any]] = None,
) -> None:
    debug_dir = _resolve_recording_snapshot_debug_dir()
    if not debug_dir:
        return

    try:
        debug_context = dict(debug_context or {})
        target_dir = _resolve_recording_snapshot_debug_path(debug_dir, debug_context=debug_context)
        target_dir.mkdir(parents=True, exist_ok=True)
        sequence = _next_debug_sequence(target_dir)
        label = str(plan.get("description") or instruction or stage)
        json_path = target_dir / _debug_filename(
            sequence=sequence,
            stage=stage,
            kind="attempt",
            label=label,
            extension="json",
        )
        code = str(plan.get("code") or "")
        payload: Dict[str, Any] = {
            "stage": stage,
            "debug_context": debug_context,
            "instruction": instruction,
            "page": page_state,
            "plan": _safe_jsonable(plan),
            "generated_code": code,
            "execution_result": _safe_jsonable(execution_result),
        }
        if failure_analysis:
            payload["failure_analysis"] = failure_analysis
        if code:
            code_path = target_dir / _debug_filename(
                sequence=sequence,
                stage=stage,
                kind="code",
                label=label,
                extension="py",
            )
            code_path.write_text(code, encoding="utf-8")
            payload["generated_code_path"] = str(code_path)
        json_path.write_text(
            json.dumps(_safe_jsonable(payload), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("[RPA-DIAG] attempt dump written stage=%s path=%s", stage, json_path)
    except Exception:
        logger.warning("[RPA-DIAG] attempt dump failed stage=%s", stage, exc_info=True)
        return


def _write_recording_planner_failure_debug(
    stage: str,
    *,
    instruction: str,
    page_state: Dict[str, Any],
    raw_snapshot: Optional[Dict[str, Any]],
    compact_snapshot: Dict[str, Any],
    exception: BaseException,
    model_config: Optional[Dict[str, Any]] = None,
    debug_context: Optional[Dict[str, Any]] = None,
) -> None:
    debug_dir = _resolve_recording_snapshot_debug_dir()
    if not debug_dir:
        return

    try:
        debug_context = dict(debug_context or {})
        target_dir = _resolve_recording_snapshot_debug_path(debug_dir, debug_context=debug_context)
        target_dir.mkdir(parents=True, exist_ok=True)
        sequence = _next_debug_sequence(target_dir)
        json_path = target_dir / _debug_filename(
            sequence=sequence,
            stage=stage,
            kind="planner_failure",
            label=instruction or stage,
            extension="json",
        )
        raw_output = str(getattr(exception, "raw_output", "") or "")
        llm_call = getattr(exception, "llm_call", None)
        raw_snapshot = raw_snapshot or {}
        payload: Dict[str, Any] = {
            "stage": stage,
            "debug_context": debug_context,
            "instruction": instruction,
            "page": page_state,
            "exception": {
                "type": type(exception).__name__,
                "message": str(exception),
            },
            "model_config": _model_config_summary(model_config),
            "compact_snapshot_summary": _compact_snapshot_debug_summary(compact_snapshot),
            "snapshot_comparison": _compare_instruction_snapshot_presence(
                instruction,
                raw_snapshot,
                compact_snapshot,
            ),
        }
        if raw_snapshot:
            payload["raw_snapshot_summary"] = _build_snapshot_debug_metrics(raw_snapshot, compact_snapshot)[
                "raw_snapshot"
            ]
        if raw_output:
            payload["planner_raw_output"] = _text_diagnostic(raw_output, limit=12000)
        if isinstance(llm_call, dict) and llm_call:
            payload["llm_call"] = _safe_jsonable(llm_call)
        json_path.write_text(
            json.dumps(_safe_jsonable(payload), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("[RPA-DIAG] planner failure dump written stage=%s path=%s", stage, json_path)
    except Exception:
        logger.warning("[RPA-DIAG] planner failure dump failed stage=%s", stage, exc_info=True)
        return


def _build_snapshot_debug_metrics(raw_snapshot: Dict[str, Any], compact_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    content_nodes = list(raw_snapshot.get("content_nodes") or [])
    actionable_nodes = list(raw_snapshot.get("actionable_nodes") or [])
    containers = list(raw_snapshot.get("containers") or [])
    expanded_regions = list(compact_snapshot.get("expanded_regions") or [])
    sampled_regions = list(compact_snapshot.get("sampled_regions") or [])
    catalogue = list(compact_snapshot.get("region_catalogue") or [])
    table_views = list(compact_snapshot.get("table_views") or [])
    detail_views = list(compact_snapshot.get("detail_views") or [])
    return {
        "raw_snapshot": {
            "frame_count": len(raw_snapshot.get("frames") or []),
            "content_node_count": len(content_nodes),
            "actionable_node_count": len(actionable_nodes),
            "container_count": len(containers),
            "content_node_limit_hit": len(content_nodes) >= 160,
            "actionable_node_limit_hit": len(actionable_nodes) >= 120,
            "semantic_kind_counts": _count_by_key(content_nodes, "semantic_kind"),
            "container_kind_counts": _count_by_key(containers, "container_kind"),
        },
        "compact_snapshot": {
            "mode": compact_snapshot.get("mode", ""),
            "char_size": len(json.dumps(_safe_jsonable(compact_snapshot), ensure_ascii=False, sort_keys=True, default=str)),
            "expanded_region_count": len(expanded_regions),
            "sampled_region_count": len(sampled_regions),
            "catalogue_region_count": len(catalogue),
            "table_view_count": len(table_views),
            "detail_view_count": len(detail_views),
            "expanded_region_titles": _region_titles(expanded_regions),
            "sampled_region_titles": _region_titles(sampled_regions),
            "table_view_titles": _region_titles(table_views),
            "detail_view_titles": [
                str(view.get("section_title") or view.get("title") or "").strip()[:120]
                for view in detail_views[:20]
                if str(view.get("section_title") or view.get("title") or "").strip()
            ],
            "region_kind_counts": _count_by_key(expanded_regions + sampled_regions + catalogue, "kind"),
        },
    }


def _compact_snapshot_debug_summary(compact_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    expanded_regions = list(compact_snapshot.get("expanded_regions") or [])
    sampled_regions = list(compact_snapshot.get("sampled_regions") or [])
    catalogue = list(compact_snapshot.get("region_catalogue") or [])
    table_views = list(compact_snapshot.get("table_views") or [])
    detail_views = list(compact_snapshot.get("detail_views") or [])
    form_views = list(compact_snapshot.get("form_views") or [])
    return {
        "mode": compact_snapshot.get("mode", ""),
        "url": compact_snapshot.get("url", ""),
        "title": compact_snapshot.get("title", ""),
        "region_scope": _safe_jsonable(compact_snapshot.get("region_scope") or {}),
        "char_size": len(json.dumps(_safe_jsonable(compact_snapshot), ensure_ascii=False, sort_keys=True, default=str)),
        "expanded_region_count": len(expanded_regions),
        "sampled_region_count": len(sampled_regions),
        "catalogue_region_count": len(catalogue),
        "table_view_count": len(table_views),
        "detail_view_count": len(detail_views),
        "form_view_count": len(form_views),
        "expanded_region_titles": _region_titles(expanded_regions),
        "sampled_region_titles": _region_titles(sampled_regions),
        "catalogue_region_titles": _region_titles(catalogue),
        "table_view_titles": _region_titles(table_views),
        "detail_view_titles": [
            str(view.get("section_title") or view.get("title") or "").strip()[:120]
            for view in detail_views[:20]
            if str(view.get("section_title") or view.get("title") or "").strip()
        ],
    }


def _compare_instruction_snapshot_presence(
    instruction: str,
    raw_snapshot: Dict[str, Any],
    compact_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    terms = _diagnostic_instruction_terms(instruction)
    if not terms:
        return {"classification": "no_instruction_terms", "terms": []}

    raw_text = _diagnostic_text_blob(raw_snapshot)
    compact_text = _diagnostic_text_blob(compact_snapshot)
    raw_hits = [term for term in terms if term in raw_text]
    compact_hits = [term for term in terms if term in compact_text]
    if raw_hits and compact_hits:
        classification = "present_in_both"
    elif raw_hits and not compact_hits:
        classification = "missing_in_compact"
    elif not raw_hits:
        classification = "missing_in_raw"
    else:
        classification = "present_in_compact_only"
    return {
        "classification": classification,
        "terms": terms,
        "raw_hits": raw_hits,
        "compact_hits": compact_hits,
    }


def _count_by_key(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _region_titles(regions: List[Dict[str, Any]]) -> List[str]:
    titles: List[str] = []
    for region in regions[:20]:
        title = str(region.get("title") or region.get("summary") or region.get("region_id") or "").strip()
        if title:
            titles.append(title[:120])
    return titles


def _diagnostic_instruction_terms(instruction: str) -> List[str]:
    text = _normalize_debug_text(instruction)
    terms: List[str] = []
    for match in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text):
        terms.append(match)
    compact_cjk = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    if len(compact_cjk) >= 4:
        terms.append(compact_cjk)
    for index in range(max(len(compact_cjk) - 1, 0)):
        gram = compact_cjk[index : index + 2]
        if gram:
            terms.append(gram)
    seen: set[str] = set()
    deduped: List[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped[:30]


def _diagnostic_text_blob(value: Any) -> str:
    return _normalize_debug_text(json.dumps(_safe_jsonable(value), ensure_ascii=False, default=str))


def _normalize_debug_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _resolve_recording_snapshot_debug_dir() -> str:
    debug_dir = str(os.environ.get("RPA_RECORDING_DEBUG_SNAPSHOT_DIR") or "").strip()
    if debug_dir:
        return debug_dir

    try:
        from backend.config import settings

        return str(getattr(settings, "rpa_recording_debug_snapshot_dir", "") or "").strip()
    except Exception:
        return ""


def _resolve_recording_snapshot_debug_path(debug_dir: str, *, debug_context: Optional[Dict[str, Any]] = None) -> Path:
    path = Path(str(debug_dir or "").strip()).expanduser()
    resolved = path if path.is_absolute() else Path(__file__).resolve().parents[3] / path
    session_id = str((debug_context or {}).get("session_id") or "").strip()
    if not session_id:
        return resolved
    return resolved / _safe_debug_path_segment(session_id)


def _next_debug_sequence(target_dir: Path) -> int:
    max_seen = 0
    for pattern in (
        "*-snapshot-*.json",
        "*-attempt-*.json",
        "*-planner_failure-*.json",
        "*-code-*.py",
        "snapshot-*.json",
        "attempt-*.json",
        "planner_failure-*.json",
        "code-*.py",
    ):
        for path in target_dir.glob(pattern):
            match = re.match(r"^(?:snapshot|attempt|code)-(\d+)-|^(\d+)-", path.name)
            if match:
                max_seen = max(max_seen, int(match.group(1) or match.group(2)))
    return max_seen + 1


def _debug_filename(*, sequence: int, stage: str, kind: str, label: str, extension: str) -> str:
    stage_segment = _safe_debug_path_segment(stage, max_length=40, allow_unicode=False)
    label_segment = _safe_debug_path_segment(label, max_length=48, allow_unicode=True)
    return f"{sequence:03d}-{stage_segment}-{kind}-{label_segment}.{extension}"


def _safe_debug_path_segment(value: str, *, max_length: int = 120, allow_unicode: bool = False) -> str:
    pattern = r"[^\w\u4e00-\u9fff_.-]+" if allow_unicode else r"[^a-zA-Z0-9_.-]+"
    segment = re.sub(pattern, "_", str(value or "").strip(), flags=re.UNICODE)
    segment = segment.strip("._")
    return segment[:max_length] or "unknown"


def _safe_jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except Exception:
        return str(value)

