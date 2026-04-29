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
from urllib.parse import unquote, urljoin, urlparse
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


logger = logging.getLogger(__name__)


_GENERATED_CODE_FILENAME = "<recording_runtime_agent>"
_RANDOM_LIKE_ATTR_RE = re.compile(r"(?i)(?:[a-z]+[-_])?[a-z0-9]{6,}[a-z][a-z0-9]*")
_DOWNLOAD_EVENT_DRAIN_TIMEOUT_S = 0.5


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
  "input_bindings": {"param_name": {"source": "user_param|previous_result|literal", "default": "recorded sample value", "classification": "user_param|dynamic|literal"}},
  "output_bindings": {"field_name": {"path": "output.path"}},
  "postcondition": {"kind": "table_row_exists", "source": "observed", "table_headers": ["<observed column>"], "key": {"<observed id column>": "{{param_name}}"}, "expect": {"<observed status column>": "<observed terminal value>"}},
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
- If the user asks to filter/search and open a specific record, do not stop after the record is merely visible in a list/table. Click the row-local link/action or stable record locator, then confirm a detail page, detail panel, selected row expansion, or URL/detail-view change.
- If the requested data is already visible in snapshot.detail_views, prefer action_type="extract_snapshot" and expected_effect="extract" even when the instruction mentions opening or entering a detail page.
- When snapshot.modal_dialogs is non-empty, the active dialog is the current interaction scope. Continue inside that dialog instead of clicking background page controls to reopen it.
- If code is returned, it must define async def run(page, results).
- Use action_type="extract_snapshot" only when the requested extract-only data is already present in snapshot.detail_views fields.
- For extract_snapshot, return the relevant observed detail fields in the plan itself, including the detail view frame_path when present; do not generate Python code and do not reference `snapshot` inside `run()`.
- Use input_bindings for values that should vary at replay time. Keep literal UI labels, headers, button names, and fixed workflow labels out of input_bindings.
- Use postcondition only as a candidate replayable structural check that was observed from the current page or returned output; include source="observed". It must be anchored to input_bindings such as "{{param_name}}" and to real table/detail headers visible in snapshot evidence. Do not encode guessed status values, examples, or business-specific recovery rules.
- Use output_bindings only to describe returned output paths; generated Python still returns the current step output normally.
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
- For in-page filter/search forms, fill only editable controls such as textbox/searchbox/combobox/input/textarea/contenteditable; do not fill buttons or submit controls even if their test id or text contains the query concept.
- Treat same-page filtering, sorting, modal submission, and table/list refreshes as expected_effect="mixed" or "extract" unless the user explicitly requires the browser URL to change.
- Do not leave the browser on API, JSON, raw, or other machine endpoints after an extract-only command.
- For extract-only commands, prefer user-facing pages and restore the most recent user-facing page after any temporary helper navigation.
- For extract-only commands, prefer snapshot.expanded_regions and snapshot.sampled_regions before broad DOM scans.
- When transferring data from one page to another, prefer structured snapshot.detail_views fields as the source of truth. Do not parse the whole body text with broad regular expressions when structured label/value fields are available.
- Use the region title, heading, or catalogue summary as context when it matches the requested area.
- If an expanded region is a label_value_group and the user asks for field names or values, keep extraction focused on that region or supporting locator evidence instead of scanning every table.
- Avoid treating tables as the default fallback for field extraction when a more relevant label_value_group is present.
- snapshot.region_catalogue is page context only.
- Structured snapshot views:
  - For table/list/grid tasks, inspect `snapshot.table_views` before generic `expanded_regions`.
  - `table_views[].columns` describes column ids, headers, and inferred roles.
  - `table_views[].rows[].cells` describes row-local cell text and row-local actions.
  - `table_views[].rows[].cells[].controls` describes editable controls inside a cell. For editable tables, map intended values to column headers and use the row-relative control locator before falling back to raw input order.
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
- For extract-only commands, do not return null/empty output unless the user explicitly allows empty results.
- Set allow_empty_output=true only when the user explicitly says no result, empty list, or empty output is acceptable.
- During repair, treat raw error logs and current page facts as authoritative. Any failure_analysis.hint is advisory only.
- 修复规则：
  - 修复时必须优先参考原始错误日志、异常类型、traceback 行号和当前页面事实。
  - 修复前先判断失败类型：如果失败来自 Python 代码错误，应优先修复对应代码行；如果失败来自页面状态、定位器、空数据或目标区域选择错误，再调整 selector 或取数策略。
  - 修复时应保持用户原始目标不变，不要把一次局部代码错误扩展成无关的页面流程重写。
- During repair after a fill/click actionability failure, inspect the page after failure and visible candidates before retrying the selector.
- If a click failed because another element or dialog intercepts pointer events, assume the target dialog is already open. Continue inside the visible dialog/overlay/current focused form instead of clicking the background trigger again.
- For state-changing or artifact-producing commands, prefer short bounded waits for a business-visible terminal condition such as a success message, row appearing in a list, status changing out of processing/pending, final URL leaving the edit page, or a download event, then return the observed state.
- For state-changing or artifact-producing commands, return observed state after the action, not just intended constants or an acknowledgement. Re-read the visible row/detail/form, success message, status text, generated file name, or download event before reporting success.
- If a required terminal condition is not reached (for example not complete, not ready, no download, validation failed, or saved values do not match the intended values), raise RuntimeError with the observed state instead of returning success.
- Status values may be localized labels or raw enum tokens. Treat exact visible enum/status tokens from the page as authoritative terminal evidence; do not require translated synonyms that are not visible.
- After saving an edit form, list rows may only show summary columns. If some saved fields are not visible in the list, reopen the row detail/edit view or inspect the visible dialog before failing; do not require hidden fields to appear in a summary row.
- For multi-part commands, do not return after an intermediate milestone such as opening an edit dialog, showing a creation form, selecting a row, or making a target visible. Continue until every requested verb in the command has an observed terminal state.
- For asynchronous job/report flows that say to wait until completion or download a file, continue bounded polling until a completed/ready/downloadable state is visible or a browser download event fires. Do not return `downloaded: false`, `not_confirmed_complete`, or similar incomplete states as successful output.
- For asynchronous job/report flows, distinguish label/value description tables from result tables. If a completed state and filename are visible in a description panel, locate the associated row/action or page-level download control and require `page.expect_download()` before returning success.
- Use short bounded waits during recording; do not poll for minutes. If the terminal state is not reached quickly, return the best observed state instead of entering a long loop.
- For editable table or line-item forms, do not unconditionally add a new row. First inspect existing editable rows, reuse an empty/default row when available, fill by column/header/label semantics rather than raw input order, and verify row count or computed totals before submitting when those values are visible. Do not leave blank required line rows behind; fill them, remove them, or fail before submit with the observed blank cells.
- For create/submit forms, after clicking submit/save, verify that the browser left the editable form or that a success message/new record identifier/status is visible. If the page remains on the same form with blank required controls or validation text, raise RuntimeError instead of returning success.
- Do not click unnamed increment/decrement controls repeatedly for numeric fields. Prefer filling the numeric input directly after selecting/clearing it, or read the current value and set the exact target value.
- For input[type=number] or role=spinbutton, fill only numeric strings. If the intended value is not numeric, the target is a different field; re-select by row header, label, placeholder, aria name, or nearby text before filling.
- Avoid broad positional form filling. When a form or editable table has labels, placeholders, aria names, data attributes, column headers, or row-local controls, map values to those semantic anchors first and use raw input order only as a last resort.
- In dialogs and forms, scope field locators to the dialog/form container and prefer stable data-testid/role/placeholder locators. Avoid bare page.get_by_label(...) when the same label can match the dialog title or multiple controls.
- For empty-result filter/search tasks, absence of the searched value in rows is not enough. Verify zero data rows, a visible empty-state message, or row count reduction to zero after the filter; if unrelated rows remain visible, raise RuntimeError with the observed rows.
- Do not pass Python lambda or other callables as Playwright locator name/has_text filters; Playwright Python expects strings, regex patterns, or supported options.
"""


class RecordingAgentResult(BaseModel):
    success: bool
    trace: Optional[RPAAcceptedTrace] = None
    traces: List[RPAAcceptedTrace] = Field(default_factory=list)
    diagnostics: List[RPATraceDiagnostic] = Field(default_factory=list)
    output_key: Optional[str] = None
    output: Any = None
    message: str = ""


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

    async def run(
        self,
        *,
        page: Any,
        instruction: str,
        runtime_results: Optional[Dict[str, Any]] = None,
        debug_context: Optional[Dict[str, Any]] = None,
    ) -> RecordingAgentResult:
        runtime_results = runtime_results if runtime_results is not None else {}
        debug_context = dict(debug_context or {})
        before = await _page_state(page)
        snapshot = await _safe_page_snapshot(page)
        compact_snapshot = _compact_snapshot(snapshot, instruction)
        payload = {
            "instruction": instruction,
            "page": before.model_dump(mode="json"),
            "snapshot": compact_snapshot,
            "runtime_results": runtime_results,
        }
        _write_recording_snapshot_debug(
            "initial",
            instruction=instruction,
            page_state=before.model_dump(mode="json"),
            raw_snapshot=snapshot,
            compact_snapshot=compact_snapshot,
            runtime_results=runtime_results,
            debug_context=debug_context,
        )

        first_plan = _build_table_ordinal_overlay_plan(instruction, snapshot)
        if not first_plan:
            first_plan = _build_ordinal_overlay_plan(instruction, snapshot)
        if not first_plan:
            first_plan = _build_detail_extract_plan(instruction, snapshot)
        if not first_plan:
            first_plan, first_result = await self._plan_and_execute(
                page=page,
                payload=payload,
                runtime_results=runtime_results,
                instruction=instruction,
                before=before,
            )
        else:
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
            )
            return RecordingAgentResult(
                success=True,
                trace=trace,
                traces=[trace],
                output_key=trace.output_key,
                output=trace.output,
                message="Recording command completed.",
            )

        failed_page = await _page_state(page)
        failed_snapshot = await _safe_page_snapshot(page)
        compact_failed_snapshot = _compact_snapshot(failed_snapshot, instruction)
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
            "snapshot_after_failure": _safe_jsonable(compact_failed_snapshot),
        }
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
            "snapshot_after_failure": compact_failed_snapshot,
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
        repair_plan, repair_result = await self._plan_and_execute(
            page=page,
            payload=repair_payload,
            runtime_results=runtime_results,
            instruction=instruction,
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
            )
            return RecordingAgentResult(
                success=True,
                trace=trace,
                traces=[trace],
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
        second_failed_page = await _page_state(page)
        second_failed_snapshot = await _safe_page_snapshot(page)
        compact_second_failed_snapshot = _compact_snapshot(second_failed_snapshot, instruction)
        second_repair_context = {
            "error": repair_error,
            "failed_plan": repair_plan,
            "page_after_failure": second_failed_page.model_dump(mode="json"),
            "snapshot_after_failure": compact_second_failed_snapshot,
            "previous_failures": [diagnostic.message for diagnostic in diagnostics],
        }
        if repair_error_type:
            second_repair_context["error_type"] = repair_error_type
        if repair_traceback:
            second_repair_context["traceback"] = repair_traceback
        if repair_known_failure_analysis:
            second_repair_context["failure_analysis"] = repair_known_failure_analysis
        second_repair_payload = {
            **payload,
            "repair": second_repair_context,
        }
        second_repair_plan, second_repair_result = await self._plan_and_execute(
            page=page,
            payload=second_repair_payload,
            runtime_results=runtime_results,
            instruction=instruction,
            before=before,
        )
        _write_recording_attempt_debug(
            "second_repair_attempt",
            instruction=instruction,
            page_state=second_failed_page.model_dump(mode="json"),
            plan=second_repair_plan,
            execution_result=second_repair_result,
            failure_analysis=None if second_repair_result.get("success") else _known_failure_analysis(second_repair_result.get("error")),
            debug_context=debug_context,
        )
        if second_repair_result.get("success"):
            trace = await self._accepted_trace(
                page,
                instruction,
                second_repair_plan,
                second_repair_result,
                before,
                repair_attempted=True,
                snapshot=second_failed_snapshot,
            )
            return RecordingAgentResult(
                success=True,
                trace=trace,
                traces=[trace],
                diagnostics=diagnostics,
                output_key=trace.output_key,
                output=trace.output,
                message="Recording command completed after repair.",
            )

        second_repair_error = str(second_repair_result.get("error") or "recording command repair failed")
        second_repair_error_type = str(second_repair_result.get("error_type") or "").strip()
        second_repair_traceback = str(second_repair_result.get("traceback") or "").strip()
        second_repair_known_failure_analysis = _known_failure_analysis(second_repair_error)
        second_repair_diagnostic_raw = {
            "plan": _safe_jsonable(second_repair_plan),
            "result": _safe_jsonable(second_repair_result),
        }
        if second_repair_error_type:
            second_repair_diagnostic_raw["error_type"] = second_repair_error_type
        if second_repair_traceback:
            second_repair_diagnostic_raw["traceback"] = second_repair_traceback
        if second_repair_known_failure_analysis:
            second_repair_diagnostic_raw["failure_analysis"] = second_repair_known_failure_analysis
        diagnostics.append(
            RPATraceDiagnostic(
                source="ai",
                message=second_repair_error,
                raw=second_repair_diagnostic_raw,
            )
        )
        return RecordingAgentResult(
            success=False,
            diagnostics=diagnostics,
            message="Recording command failed after two repairs.",
        )

    async def _plan_and_execute(
        self,
        *,
        page: Any,
        payload: Dict[str, Any],
        runtime_results: Dict[str, Any],
        instruction: str,
        before: RPAPageState,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        try:
            plan = await self.planner(payload)
        except Exception as exc:
            plan = {
                "description": "Planner output could not be executed",
                "action_type": "planner_error",
                "expected_effect": "none",
            }
            return plan, {
                "success": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "traceback": _format_exception_for_repair(exc),
                "output": "",
            }
        result = await self.executor(page, plan, runtime_results)
        result = await _ensure_expected_effect(
            page=page,
            instruction=instruction,
            plan=plan,
            result=result,
            before=before,
        )
        return plan, result

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
    ) -> RPAAcceptedTrace:
        after = await _page_state(page)
        result = _enrich_extract_snapshot_result_with_replay_evidence(result, snapshot or {})
        output = result.get("output")
        output_key = _normalize_result_key(plan.get("output_key"))
        locator_stability = _build_locator_stability_metadata(plan, snapshot or {})
        signals = _merge_runtime_ai_signal(dict(result.get("signals") or {}), plan)
        input_bindings = _dict_field(plan.get("input_bindings"))
        output_bindings = _dict_field(plan.get("output_bindings"))
        postcondition = await _trusted_replay_postcondition(
            page=page,
            plan=plan,
            result=result,
            input_bindings=input_bindings,
        )
        return RPAAcceptedTrace(
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            user_instruction=instruction,
            description=str(plan.get("description") or instruction),
            before_page=before,
            after_page=after,
            signals=signals,
            output_key=output_key,
            output=output,
            ai_execution=RPAAIExecution(
                language="snapshot" if str(plan.get("action_type") or "").strip() == "extract_snapshot" else "python",
                code=_extract_snapshot_preview_code(plan) if str(plan.get("action_type") or "").strip() == "extract_snapshot" else str(plan.get("code") or ""),
                output=output,
                error=result.get("error"),
                repair_attempted=repair_attempted,
            ),
            locator_stability=locator_stability,
            input_bindings=input_bindings,
            output_bindings=output_bindings,
            postcondition=postcondition,
        )

    async def _default_planner(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from backend.deepagent.engine import get_llm_model
        from langchain_core.messages import HumanMessage, SystemMessage

        model = get_llm_model(config=self.model_config, streaming=False)
        response = await model.ainvoke(
            [
                SystemMessage(content=RECORDING_RUNTIME_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ]
        )
        return _parse_json_object(_extract_text(response))

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
                await page.locator(selector).first.click()
                return {"success": True, "output": "clicked", "effect": {"type": "click", "action_performed": True}}

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
            code = _normalize_generated_playwright_code(code)
            plan["code"] = code
            if "async def run(page, results)" not in code:
                return {"success": False, "error": "plan missing async def run(page, results)", "output": ""}
            namespace: Dict[str, Any] = {}
            _cache_generated_code_for_traceback(code)
            exec(compile(code, _GENERATED_CODE_FILENAME, "exec"), namespace, namespace)
            runner = namespace.get("run")
            if not callable(runner):
                return {"success": False, "error": "No run(page, results) function defined", "output": ""}
            navigation_history: List[str] = []
            download_events: List[Dict[str, Any]] = []
            download_observed = asyncio.get_running_loop().create_future()
            original_goto = getattr(page, "goto", None)
            goto_wrapped = False
            download_handler_attached = False

            def on_download(download: Any) -> None:
                download_events.append(
                    {
                        "filename": str(getattr(download, "suggested_filename", "") or ""),
                        "url": str(getattr(page, "url", "") or ""),
                    }
                )
                if not download_observed.done():
                    download_observed.set_result(True)

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

            page_on = getattr(page, "on", None)
            if callable(page_on):
                try:
                    page_on("download", on_download)
                    download_handler_attached = True
                except Exception:
                    download_handler_attached = False

            try:
                output = runner(page, runtime_results)
                if inspect.isawaitable(output):
                    output = await output
                if download_handler_attached:
                    await asyncio.sleep(0)
                    if not download_events and _should_drain_download_events(plan, code):
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(download_observed),
                                timeout=_DOWNLOAD_EVENT_DRAIN_TIMEOUT_S,
                            )
                        except asyncio.TimeoutError:
                            pass
            finally:
                if download_handler_attached:
                    remover = getattr(page, "remove_listener", None) or getattr(page, "off", None)
                    if callable(remover):
                        try:
                            remover("download", on_download)
                        except Exception:
                            pass
                if goto_wrapped:
                    try:
                        setattr(page, "goto", original_goto)
                    except Exception:
                        pass

            response = {"success": True, "error": None, "output": output}
            if navigation_history:
                response["navigation_history"] = navigation_history
            if download_events:
                download_signal = dict(download_events[0])
                download_signal["count"] = len(download_events)
                if len(download_events) > 1:
                    download_signal["files"] = list(download_events)
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
    include_empty = _normalize_bool(plan.get("include_empty"))
    for field in fields:
        label = str(field.get("label") or "").strip()
        if not label:
            continue
        visible = bool(field.get("visible", True))
        value_info = _snapshot_field_value_info(field)
        value = value_info["value"]
        if not visible and not include_hidden:
            continue
        if value == "" and not include_empty:
            continue
        output[label] = value
        selected_fields.append(
            {
                "label": label,
                "value": value,
                "observed_label": value_info["observed_label"],
                "data_prop": str(field.get("data_prop") or "").strip(),
                "visible": visible,
                "value_kind": str(field.get("value_kind") or "").strip(),
                "required": bool(field.get("required")),
                "replay_required": bool(field.get("replay_required", True)),
                "field_locator": dict(field.get("field_locator") or {}),
                "label_locator": dict(field.get("label_locator") or {}),
                "value_locator": dict(field.get("value_locator") or {}),
                "locator_hints": list(field.get("locator_hints") or [])[:3],
                "adapter": str(field.get("adapter") or field.get("framework_hint") or "").strip(),
                "value_selector": str(field.get("value_selector") or "").strip(),
                "value_selectors": list(field.get("value_selectors") or [])[:6],
            }
        )

    if not output and not _normalize_bool(plan.get("allow_empty_output")):
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


def _enrich_extract_snapshot_result_with_replay_evidence(
    result: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    signals = result.get("signals") if isinstance(result.get("signals"), dict) else {}
    extract_signal = signals.get("extract_snapshot") if isinstance(signals.get("extract_snapshot"), dict) else {}
    fields = extract_signal.get("fields") if isinstance(extract_signal.get("fields"), list) else []
    if not fields:
        return result

    enriched_fields = [
        _enrich_extract_snapshot_field_with_replay_evidence(dict(field), snapshot)
        for field in fields
        if isinstance(field, dict)
    ]
    enriched_signal = dict(extract_signal)
    enriched_signal["fields"] = enriched_fields
    enriched_signals = dict(signals)
    enriched_signals["extract_snapshot"] = enriched_signal
    enriched_result = dict(result)
    output = enriched_result.get("output")
    if isinstance(output, dict):
        enriched_output = dict(output)
        for field in enriched_fields:
            label = str(field.get("label") or "").strip()
            if label and label in enriched_output:
                enriched_output[label] = field.get("value")
        enriched_result["output"] = enriched_output
    enriched_result["signals"] = enriched_signals
    return enriched_result


def _enrich_extract_snapshot_field_with_replay_evidence(
    field: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    raw_value = str(field.get("value") or "").strip()
    if raw_value:
        observed_field = _observed_detail_field_for_label(snapshot, raw_value)
        if observed_field:
            field["value"] = str(observed_field.get("value") or "").strip()
            field["observed_label"] = str(observed_field.get("label") or "").strip()
    value_info = _snapshot_field_value_info(field)
    if value_info["value"] != field.get("value"):
        field["value"] = value_info["value"]
    observed_label = value_info["observed_label"]
    observed_label_exists = _observed_detail_label_exists(snapshot, observed_label)
    value_matched_label = _observed_detail_label_for_value(snapshot, value_info["value"])
    if value_matched_label and (not observed_label or not observed_label_exists):
        field["observed_label"] = value_matched_label
    elif observed_label and not str(field.get("observed_label") or "").strip():
        field["observed_label"] = observed_label
    value = str(value_info["value"] or "").strip()
    if not value:
        return field

    has_primary_evidence = _snapshot_field_has_replay_evidence(field)

    if not has_primary_evidence:
        url_evidence = _url_path_join_evidence(str(snapshot.get("url") or ""), value)
        if url_evidence:
            field["url_extraction"] = url_evidence
            return field

        text_pattern = _text_pattern_evidence(snapshot, value)
        if text_pattern:
            field["text_pattern"] = text_pattern
            return field

    if not isinstance(field.get("unique_text"), dict):
        unique_text = _unique_visible_text_evidence(snapshot, value)
        if unique_text:
            field["unique_text"] = unique_text
    return field


def _snapshot_field_has_replay_evidence(field: Dict[str, Any]) -> bool:
    if str(field.get("data_prop") or "").strip():
        return True
    if isinstance(field.get("field_locator"), dict) and field["field_locator"]:
        return True
    if isinstance(field.get("value_locator"), dict) and field["value_locator"]:
        return True
    if isinstance(field.get("url_extraction"), dict) and field["url_extraction"]:
        return True
    if isinstance(field.get("text_pattern"), dict) and field["text_pattern"]:
        return True
    return False


def _url_path_join_evidence(url: str, value: str) -> Dict[str, Any]:
    target = _normalize_slash_joined_text(value)
    if not target:
        return {}

    parsed = urlparse(url)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    for start in range(len(segments)):
        for count in range(1, len(segments) - start + 1):
            joined = "/".join(segments[start : start + count])
            if _normalize_slash_joined_text(joined) == target:
                return {
                    "kind": "url_path_join",
                    "start": start,
                    "count": count,
                    "separator": "/",
                }
    return {}


def _normalize_slash_joined_text(value: str) -> str:
    text = _normalize_visible_text(value)
    text = re.sub(r"\s*/\s*", "/", text)
    return text.strip("/")


def _text_pattern_evidence(snapshot: Dict[str, Any], value: str) -> Dict[str, Any]:
    target = _normalize_visible_text(value)
    if not target:
        return {}

    for node in _snapshot_text_evidence_nodes(snapshot):
        for text in _node_visible_text_candidates(node):
            pattern = _text_pattern_from_observed_value(text, target)
            if not pattern:
                continue
            role = str(node.get("role") or "").strip()
            tag = str(node.get("tag") or node.get("element_snapshot", {}).get("tag") or "").strip().lower()
            if role:
                pattern["role"] = role
            if tag:
                pattern["tag"] = tag
            pattern["value"] = value
            return pattern
    return {}


def _unique_visible_text_evidence(snapshot: Dict[str, Any], value: str) -> Dict[str, Any]:
    target = _normalize_visible_text(value)
    if not target:
        return {}

    matches: List[Dict[str, Any]] = []
    for node in _snapshot_text_evidence_nodes(snapshot):
        for text in _node_visible_text_candidates(node):
            if _normalize_visible_text(text) != target:
                continue
            role = str(node.get("role") or "").strip()
            tag = str(node.get("tag") or node.get("element_snapshot", {}).get("tag") or "").strip().lower()
            match: Dict[str, Any] = {"text": target}
            if role:
                match["role"] = role
            if tag:
                match["tag"] = tag
            if match not in matches:
                matches.append(match)
    if len(matches) != 1:
        return {}
    return matches[0]


def _snapshot_text_evidence_nodes(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for key in ("content_nodes", "actionable_nodes"):
        for node in list(snapshot.get(key) or []):
            if isinstance(node, dict):
                nodes.append(node)
    return nodes


def _node_visible_text_candidates(node: Dict[str, Any]) -> List[str]:
    element_snapshot = node.get("element_snapshot") if isinstance(node.get("element_snapshot"), dict) else {}
    raw_values = [
        node.get("text"),
        node.get("name"),
        element_snapshot.get("text"),
        element_snapshot.get("title"),
    ]
    candidates: List[str] = []
    for value in raw_values:
        text = _normalize_visible_text(value)
        if text and text not in candidates:
            candidates.append(text)
    return candidates


def _text_pattern_from_observed_value(text: str, value: str) -> Dict[str, Any]:
    normalized_text = _normalize_visible_text(text)
    normalized_value = _normalize_visible_text(value)
    index = normalized_text.find(normalized_value)
    if index < 0:
        return {}
    prefix = normalized_text[:index].strip()
    suffix = normalized_text[index + len(normalized_value) :].strip()
    if not prefix and not suffix:
        return {}
    return {
        "prefix": prefix[-80:],
        "suffix": suffix[:80],
    }


def _normalize_visible_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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
        return [_normalize_snapshot_plan_field(dict(field)) for field in fields if isinstance(field, dict)]
    if isinstance(fields, dict):
        return _snapshot_field_map_to_list(fields)
    extraction = plan.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("fields"), list):
        return [_normalize_snapshot_plan_field(dict(field)) for field in extraction["fields"] if isinstance(field, dict)]
    if isinstance(extraction, dict) and isinstance(extraction.get("fields"), dict):
        return _snapshot_field_map_to_list(extraction["fields"])
    return []


def _snapshot_field_map_to_list(fields: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for label, value in fields.items():
        label_text = str(label or "").strip()
        if not label_text:
            continue
        normalized.append(_normalize_snapshot_plan_field({"label": label_text, "value": value}))
    return normalized


def _normalize_snapshot_plan_field(field: Dict[str, Any]) -> Dict[str, Any]:
    value_info = _snapshot_field_value_info(field)
    if value_info["value"] != field.get("value"):
        field["value"] = value_info["value"]
    if value_info["observed_label"] and not str(field.get("observed_label") or "").strip():
        field["observed_label"] = value_info["observed_label"]
    return field


def _snapshot_field_value_info(field: Dict[str, Any]) -> Dict[str, str]:
    raw_value = field.get("value")
    observed_label = str(field.get("observed_label") or "").strip()
    if isinstance(raw_value, dict):
        nested_label = str(raw_value.get("label") or "").strip()
        nested_value = raw_value.get("value")
        return {
            "value": str(nested_value or "").strip(),
            "observed_label": observed_label or nested_label,
        }
    return {"value": str(raw_value or "").strip(), "observed_label": observed_label}


def _observed_detail_label_for_value(snapshot: Dict[str, Any], value: str) -> str:
    target = _normalize_visible_text(value)
    if not target:
        return ""
    for detail in list(snapshot.get("detail_views") or []):
        if not isinstance(detail, dict):
            continue
        for field in list(detail.get("fields") or []):
            if not isinstance(field, dict):
                continue
            field_value = _normalize_visible_text(field.get("value"))
            label = str(field.get("label") or "").strip()
            if label and field_value == target:
                return label
    return ""


def _observed_detail_label_exists(snapshot: Dict[str, Any], label: str) -> bool:
    target = _normalize_visible_text(label)
    if not target:
        return False
    for detail in list(snapshot.get("detail_views") or []):
        if not isinstance(detail, dict):
            continue
        for field in list(detail.get("fields") or []):
            if not isinstance(field, dict):
                continue
            if _normalize_visible_text(field.get("label")) == target:
                return True
    return False


def _observed_detail_field_for_label(snapshot: Dict[str, Any], label: str) -> Dict[str, Any]:
    target = _normalize_visible_text(label)
    if not target:
        return {}
    for detail in list(snapshot.get("detail_views") or []):
        if not isinstance(detail, dict):
            continue
        for field in list(detail.get("fields") or []):
            if not isinstance(field, dict):
                continue
            field_label = _normalize_visible_text(field.get("label"))
            field_value = _normalize_visible_text(field.get("value"))
            if field_label == target and field_value:
                return field
    return {}


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
    candidates = _json_object_candidates(raw)
    last_error: Optional[Exception] = None
    validation_error: Optional[ValueError] = None
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for start in (index for index, char in enumerate(candidate) if char == "{"):
            try:
                parsed, _end = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                try:
                    return _normalize_planner_object(parsed)
                except ValueError as exc:
                    if _looks_like_planner_object(parsed):
                        raise exc
                    if validation_error is None:
                        validation_error = exc
                    continue
    if validation_error:
        raise validation_error
    if last_error:
        raise last_error
    raise ValueError("Recording planner must return a JSON object")


def _normalize_planner_object(parsed: Dict[str, Any]) -> Dict[str, Any]:
    parsed = dict(parsed)
    parsed.setdefault("action_type", "run_python")
    parsed["expected_effect"] = _normalize_expected_effect(parsed.get("expected_effect"))
    parsed["allow_empty_output"] = _normalize_bool(parsed.get("allow_empty_output"))
    parsed["input_bindings"] = _dict_field(parsed.get("input_bindings"))
    parsed["output_bindings"] = _dict_field(parsed.get("output_bindings"))
    parsed["postcondition"] = _dict_field(parsed.get("postcondition"))
    if parsed.get("action_type") == "run_python" and "async def run(page, results)" not in str(parsed.get("code") or ""):
        raise ValueError("Recording planner must return Python code defining async def run(page, results)")
    return parsed


def _looks_like_planner_object(parsed: Dict[str, Any]) -> bool:
    planner_keys = {
        "description",
        "action_type",
        "expected_effect",
        "effect",
        "allow_empty_output",
        "output_key",
        "code",
        "source",
        "section_title",
        "frame_path",
        "fields",
        "extraction",
        "input_bindings",
        "output_bindings",
        "postcondition",
    }
    return any(key in parsed for key in planner_keys)


def _dict_field(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


async def _trusted_replay_postcondition(
    *,
    page: Any,
    plan: Dict[str, Any],
    result: Dict[str, Any],
    input_bindings: Dict[str, Any],
) -> Dict[str, Any]:
    candidate = _postcondition_candidate(plan, result)
    if not candidate:
        return {}
    if not _postcondition_has_parameterized_key(candidate, input_bindings):
        return {}
    snapshot = await _safe_page_snapshot(page)
    return _validated_postcondition(candidate, snapshot=snapshot, input_bindings=input_bindings)


def _postcondition_candidate(plan: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    signals = result.get("signals")
    if isinstance(signals, dict):
        signaled = _dict_field(signals.get("postcondition"))
        if signaled:
            return signaled
    return _dict_field(plan.get("postcondition"))


def _validated_postcondition(
    value: Any,
    *,
    snapshot: Optional[Dict[str, Any]] = None,
    input_bindings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    postcondition = _dict_field(value)
    if not postcondition:
        return {}
    source = str(postcondition.get("source") or postcondition.get("evidence_source") or "").strip().lower()
    observed = _normalize_bool(postcondition.get("observed"))
    if source not in {"observed", "snapshot", "structured_snapshot", "page"} and not observed:
        return {}
    if str(postcondition.get("kind") or "").strip() != "table_row_exists":
        return {}
    input_bindings = input_bindings or {}
    if not _postcondition_has_parameterized_key(postcondition, input_bindings):
        return {}
    if snapshot is not None and not _snapshot_contains_postcondition_row(snapshot, postcondition, input_bindings):
        return {}
    return postcondition


_POSTCONDITION_REF_RE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}$")


def _postcondition_has_parameterized_key(postcondition: Dict[str, Any], input_bindings: Dict[str, Any]) -> bool:
    key = postcondition.get("key")
    if not isinstance(key, dict) or not key:
        return False
    for raw_value in key.values():
        ref = _postcondition_ref_name(raw_value)
        if ref and ref.split(".", 1)[0] in input_bindings:
            return True
    return False


def _postcondition_ref_name(value: Any) -> str:
    match = _POSTCONDITION_REF_RE.match(str(value or "").strip())
    return match.group(1) if match else ""


def _snapshot_contains_postcondition_row(
    snapshot: Dict[str, Any],
    postcondition: Dict[str, Any],
    input_bindings: Dict[str, Any],
) -> bool:
    required_headers = _normalized_header_set(
        list(postcondition.get("table_headers") or [])
        + list((_dict_field(postcondition.get("key"))).keys())
        + list((_dict_field(postcondition.get("expect"))).keys())
    )
    key_values = _resolve_postcondition_values(_dict_field(postcondition.get("key")), input_bindings)
    expect_values = _resolve_postcondition_values(_dict_field(postcondition.get("expect")), input_bindings)
    if not required_headers or not key_values:
        return False
    for table in _iter_snapshot_tables(snapshot):
        headers = _normalized_header_set(table.get("headers") or [])
        if required_headers and not required_headers.issubset(headers):
            continue
        for row in table.get("rows") or []:
            if _row_matches_values(row, key_values) and _row_matches_values(row, expect_values):
                return True
    return False


def _resolve_postcondition_values(values: Dict[str, Any], input_bindings: Dict[str, Any]) -> Dict[str, str]:
    resolved: Dict[str, str] = {}
    for header, raw_value in values.items():
        label = _normalize_visible_text(header)
        if not label:
            continue
        ref = _postcondition_ref_name(raw_value)
        if ref:
            binding = input_bindings.get(ref.split(".", 1)[0])
            default = binding.get("default") if isinstance(binding, dict) else None
            value = _normalize_visible_text(default)
        else:
            value = _normalize_visible_text(raw_value)
        if value:
            resolved[label] = value
    return resolved


def _iter_snapshot_tables(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    tables: List[Dict[str, Any]] = []
    for view in list(snapshot.get("table_views") or []):
        if not isinstance(view, dict):
            continue
        headers = [
            _normalize_visible_text(column.get("header"))
            for column in list(view.get("columns") or [])
            if isinstance(column, dict)
        ]
        rows = []
        for row in list(view.get("rows") or []):
            if not isinstance(row, dict):
                continue
            row_map: Dict[str, str] = {}
            for cell in list(row.get("cells") or []):
                if not isinstance(cell, dict):
                    continue
                header = _normalize_visible_text(cell.get("column_header"))
                text = _normalize_visible_text(cell.get("text"))
                if header and text:
                    row_map[header] = text
            if row_map:
                rows.append(row_map)
        tables.append({"headers": headers, "rows": rows})
    for region in list(snapshot.get("expanded_regions") or []):
        if not isinstance(region, dict) or str(region.get("kind") or "") != "table":
            continue
        evidence = region.get("evidence") if isinstance(region.get("evidence"), dict) else {}
        headers = [_normalize_visible_text(item) for item in list(evidence.get("headers") or [])]
        rows = []
        for row in list(evidence.get("sample_rows") or []):
            if isinstance(row, dict):
                row_map = {
                    _normalize_visible_text(key): _normalize_visible_text(value)
                    for key, value in row.items()
                    if _normalize_visible_text(key) and _normalize_visible_text(value)
                }
                if row_map:
                    rows.append(row_map)
        tables.append({"headers": headers, "rows": rows})
    return tables


def _normalized_header_set(headers: List[Any]) -> set[str]:
    return {_normalize_visible_text(header) for header in headers if _normalize_visible_text(header)}


def _row_matches_values(row: Dict[str, str], expected: Dict[str, str]) -> bool:
    for header, value in expected.items():
        cell = _normalize_visible_text(row.get(header))
        if cell != value:
            return False
    return True


def _json_object_candidates(raw: str) -> List[str]:
    candidates: List[str] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE):
        candidate = str(match.group(1) or "").strip()
        if candidate:
            candidates.append(candidate)
    candidates.append(raw)
    return candidates


def _build_detail_extract_plan(instruction: str, snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _instruction_is_detail_extract_only(instruction):
        return None

    all_fields: List[Dict[str, Any]] = []
    section_titles: List[str] = []
    seen: set[tuple[str, str]] = set()
    for detail in list(snapshot.get("detail_views") or []):
        section_title = str(detail.get("section_title") or "").strip()
        if section_title:
            section_titles.append(section_title)
        for field in list(detail.get("fields") or []):
            label = str(field.get("label") or "").strip()
            if not label:
                continue
            visible = bool(field.get("visible", True))
            if not visible:
                continue
            value = field.get("value")
            if value in (None, ""):
                continue
            dedupe_key = (label, str(value))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            all_fields.append(
                {
                    "label": label,
                    "value": value,
                    "visible": visible,
                    "data_prop": str(field.get("data_prop") or "").strip(),
                    "value_kind": str(field.get("value_kind") or "").strip(),
                    "field_locator": dict(field.get("field_locator") or {}),
                    "label_locator": dict(field.get("label_locator") or {}),
                    "value_locator": dict(field.get("value_locator") or {}),
                    "locator_hints": list(field.get("locator_hints") or [])[:3],
                    "adapter": str(field.get("adapter") or detail.get("framework_hint") or "").strip(),
                    "value_selector": str(field.get("value_selector") or "").strip(),
                    "value_selectors": list(field.get("value_selectors") or [])[:6],
                    "replay_required": True,
                }
            )
    if not all_fields:
        return None
    return {
        "description": "Extract visible detail fields from the current page snapshot",
        "action_type": "extract_snapshot",
        "expected_effect": "extract",
        "allow_empty_output": False,
        "output_key": "detail_fields",
        "source": "detail_views",
        "section_title": " / ".join(section_titles[:3]),
        "frame_path": [],
        "fields": all_fields[:40],
    }


def _instruction_is_detail_extract_only(instruction: str) -> bool:
    text = str(instruction or "").strip().lower()
    if not text:
        return False
    if _contains_any(
        text,
        (
            "create",
            "submit",
            "save",
            "generate",
            "download",
            "fill",
            "type",
            "open",
            "click",
            "filter",
            "search",
            "query",
            "navigate",
            "go to",
            "order",
            "request",
            "新建",
            "创建",
            "提交",
            "保存",
            "生成",
            "下载",
            "填写",
            "填入",
            "打开",
            "点击",
            "筛选",
            "搜索",
            "查询",
            "进入",
            "导航",
        ),
    ):
        return False
    return _contains_any(
        text,
        (
            "extract",
            "collect",
            "read",
            "return",
            "summarize",
            "字段",
            "提取",
            "抽取",
            "读取",
            "收集",
            "返回",
        ),
    )


def _normalize_generated_playwright_code(code: str) -> str:
    normalized = str(code or "").replace(".get_by_testid(", ".get_by_test_id(")
    normalized = re.sub(
        r"\.filter\(\s*has_attribute\s*=\s*(['\"]).*?\1\s*,\s*has_text\s*=",
        ".filter(has_text=",
        normalized,
    )
    normalized = re.sub(
        r"\.filter\(\s*has_text\s*=\s*([^,\)]+)\s*,\s*has_attribute\s*=\s*(['\"]).*?\2\s*\)",
        r".filter(has_text=\1)",
        normalized,
    )
    normalized = re.sub(
        r"\.filter\(\s*has_attribute\s*=\s*(['\"]).*?\1\s*\)",
        "",
        normalized,
    )
    return normalized


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

    if "input[type=number]" in normalized or "role=\"spinbutton\"" in normalized or "role='spinbutton'" in normalized:
        return {
            "type": "numeric_input_text_mismatch",
            "hint": (
                "A number input or spinbutton was treated as the wrong field or was filled with non-numeric text. "
                "In repair, map each value to labels, column headers, row-local controls, aria names, placeholders, "
                "or nearby text before filling; only numeric strings should be filled into number inputs."
            ),
        }

    if "intercepts pointer events" in normalized or "subtree intercepts pointer" in normalized:
        return {
            "type": "active_overlay_intercepted_click",
            "hint": (
                "A visible overlay or dialog intercepted the click. In repair, do not click the same background "
                "trigger again; scope actions to the visible dialog, overlay, focused form, or its buttons."
            ),
        }

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
        if "intercepts pointer events" in normalized or "subtree intercepts pointer" in normalized:
            return {
                "type": "active_overlay_intercepted_click",
                "hint": (
                    "A visible overlay or dialog intercepted the click. In repair, do not click the same background "
                    "trigger again; scope actions to the visible dialog, overlay, focused form, or its buttons."
                ),
            }
        return {
            "type": "selector_timeout",
            "hint": (
                "The previous attempt timed out waiting for a specific selector. In repair, re-check the current "
                "page state first and consider resilient extraction through candidate link/row scanning instead "
                "of only replacing one brittle selector with another."
            ),
        }

    if "element is not an <input>" in normalized or "does not have a role allowing" in normalized:
        return {
            "type": "non_editable_fill_target",
            "hint": (
                "The fill target was not editable. In repair, first locate visible editable controls by role, tag, "
                "placeholder, label, or proximity, and keep submit/search buttons for clicking only."
            ),
        }

    if "function' object has no attribute 'replace" in normalized or 'function" object has no attribute "replace' in normalized:
        return {
            "type": "invalid_callable_locator_filter",
            "hint": (
                "The generated Playwright Python passed a callable where Playwright expects a string or regex. "
                "In repair, replace callable locator filters with explicit locator chains, text filters, or loops."
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

    if not _normalize_bool(plan.get("allow_empty_output")) and _looks_like_unsuccessful_output(result.get("output")):
        return {
            **result,
            "success": False,
            "error": "Generated command returned visible error or validation output instead of terminal success evidence.",
        }

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

        if expected_effect == "mixed":
            generic_evidence = _generic_effect_evidence(result)
            if generic_evidence:
                if _instruction_requires_terminal_write(instruction) and _is_low_information_effect_output(result.get("output")):
                    return {
                        **result,
                        "success": False,
                        "error": "Generated command stopped at an intermediate state without terminal write/save evidence.",
                    }
                effect = dict(result.get("effect") or {})
                effect.setdefault("type", "mixed")
                effect["generic_evidence"] = generic_evidence
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
        if action_type == "run_python" and _run_python_code_contains_effect(plan, expected_effect):
            generic_evidence = _generic_effect_evidence(result)
            if generic_evidence:
                effect = dict(result.get("effect") or {})
                effect.setdefault("type", expected_effect)
                effect["action_performed"] = True
                effect["generic_evidence"] = generic_evidence
                return {**result, "effect": effect}
        return {
            **result,
            "success": False,
            "error": f"Expected {expected_effect} effect, but no browser action evidence was produced.",
        }

    return result


def _run_python_code_contains_effect(plan: Dict[str, Any], expected_effect: str) -> bool:
    code = str(plan.get("code") or "")
    if expected_effect == "click":
        return any(token in code for token in (".click(", ".press(", ".check(", ".uncheck(", ".select_option("))
    if expected_effect == "fill":
        return any(token in code for token in (".fill(", ".type(", ".press_sequentially(", ".select_option("))
    return False


def _generic_effect_evidence(result: Dict[str, Any]) -> str:
    effect = result.get("effect")
    if isinstance(effect, dict) and _normalize_bool(effect.get("action_performed")):
        return "action_performed"

    signals = result.get("signals")
    if isinstance(signals, dict) and signals.get("download"):
        return "download"
    if isinstance(signals, dict) and signals.get("extract_snapshot"):
        return "extract_snapshot"

    if _has_non_empty_structured_output(result.get("output")):
        return "structured_output"

    return ""


def _instruction_requires_terminal_write(instruction: str) -> bool:
    text = str(instruction or "").lower()
    return _contains_any(
        text,
        (
            "save",
            "submit",
            "update",
            "create",
            "fill",
            "保存",
            "提交",
            "更新",
            "创建",
            "新建",
            "填写",
            "填入",
            "补全",
        ),
    )


def _is_low_information_effect_output(value: Any) -> bool:
    meaningful = [
        text
        for text in flatten_strings_for_effect(value)
        if text and not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text)
    ]
    if not meaningful:
        return True
    return all(
        re.fullmatch(r"(?:row_)?count(?:_after_\w+)?|clicked|opened|visible|found|true|false", text.lower())
        for text in meaningful
    )


def flatten_strings_for_effect(value: Any) -> List[str]:
    if isinstance(value, str):
        text = _normalize_visible_text(value)
        return [text] if text else []
    if isinstance(value, dict):
        strings: List[str] = []
        for key, item in value.items():
            strings.extend(flatten_strings_for_effect(key))
            strings.extend(flatten_strings_for_effect(item))
        return strings
    if isinstance(value, (list, tuple, set)):
        strings: List[str] = []
        for item in value:
            strings.extend(flatten_strings_for_effect(item))
        return strings
    if isinstance(value, bool):
        return [str(value)]
    if isinstance(value, (int, float)):
        return [str(value)]
    return []


def _has_non_empty_structured_output(value: Any) -> bool:
    if _looks_like_unsuccessful_output(value):
        return False
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    return False


def _looks_like_unsuccessful_output(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = {str(key).strip().lower() for key in value.keys()}
    if keys & {"error", "errors", "exception", "traceback"}:
        return True
    if _contains_nonterminal_value(value):
        return True
    return _contains_visible_error_text(value)


def _contains_nonterminal_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        text = re.sub(r"[\s_-]+", " ", value).strip().lower()
        if not text:
            return False
        return bool(
            re.search(
                r"\b(?:not confirmed|not complete|not completed|incomplete|not ready|"
                r"not downloaded|not triggered|not saved|not submitted|unconfirmed)\b",
                text,
            )
        )
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if (
                isinstance(item, bool)
                and item is False
                and any(token in key_text for token in ("download", "trigger", "match", "success", "complete", "saved", "submitted"))
            ):
                return True
            if _contains_nonterminal_value(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_contains_nonterminal_value(item) for item in value)
    return False


def _contains_visible_error_text(value: Any) -> bool:
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value).strip().lower()
        if not text:
            return False
        return bool(
            re.search(
                r"\b(?:not found|no such|missing|required|invalid|validation failed|"
                r"failed|failure|error|exception|unable to|cannot|could not|"
                r"permission denied|unauthorized|forbidden)\b",
                text,
            )
        )
    if isinstance(value, dict):
        return any(_contains_visible_error_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_visible_error_text(item) for item in value)
    return False


def _expected_effect(plan: Dict[str, Any], instruction: str) -> str:
    action_type = str(plan.get("action_type") or "").strip().lower()
    if action_type == "extract_snapshot":
        return "extract"

    explicit = _normalize_expected_effect(plan.get("expected_effect") or plan.get("effect"))
    if explicit != "extract":
        return explicit

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


async def _safe_page_snapshot(page: Any) -> Dict[str, Any]:
    try:
        return await build_page_snapshot(page, build_frame_path)
    except Exception:
        return {"url": getattr(page, "url", ""), "title": "", "frames": []}


def _compact_snapshot(snapshot: Dict[str, Any], instruction: str, limit: int = 80) -> Dict[str, Any]:
    try:
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
    for pattern in ("*-snapshot-*.json", "*-attempt-*.json", "*-code-*.py", "snapshot-*.json", "attempt-*.json", "code-*.py"):
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

