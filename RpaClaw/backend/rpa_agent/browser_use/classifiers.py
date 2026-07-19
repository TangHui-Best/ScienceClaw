"""Browser-use 0.13.2 Action 专属成功判定器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ActionJudgement:
    succeeded: bool
    reason: str


def classify_non_sop(
    action_name: str,
    params: Mapping[str, Any],
    result: object,
) -> ActionJudgement:
    error = getattr(result, "error", None)
    success = getattr(result, "success", None)
    is_done = getattr(result, "is_done", None)
    if error is not None or success is False:
        return ActionJudgement(False, "tool_reported_failure")
    if action_name == "done" and not (is_done is True and success is True):
        return ActionJudgement(False, "done_not_completed")
    if action_name == "scroll" and params.get("business_required") is False:
        return ActionJudgement(True, "planning_scroll")
    return ActionJudgement(True, "non_sop_completed")


def classify_candidate_action(
    action_name: str,
    params: Mapping[str, Any],
    result: object,
    *,
    deterministic: bool,
) -> ActionJudgement:
    """分派到动作专属后置条件；绝不以 ``error is None`` 单独成功。"""

    # Browser-use may report a page-readiness timeout after the navigation has
    # already committed. For navigation, the observed URL is the stronger,
    # deterministic postcondition and must be evaluated before the generic
    # tool-error guard. Other actions remain fail-closed on tool errors.
    if action_name == "navigate":
        data = getattr(result, "data", {})
        valid = (
            isinstance(params.get("url"), str)
            and bool(params["url"].strip())
            and data.get("url_reached") is True
        )
        if valid:
            return ActionJudgement(True, "postcondition_met")
    if getattr(result, "error", None) is not None or getattr(result, "success", None) is False:
        return ActionJudgement(False, "tool_reported_failure")
    data = getattr(result, "data", {})
    if action_name == "navigate":
        return ActionJudgement(False, "navigate_postcondition_failed")
    if action_name == "go_back":
        return _truth(data.get("history_changed"), "navigation_history_unchanged")
    if action_name == "click" and deterministic:
        return _truth(data.get("dispatched"), "click_not_dispatched")
    if action_name == "input" and deterministic:
        return ActionJudgement(
            data.get("dom_value") == params.get("text"),
            "input_value_matched" if data.get("dom_value") == params.get("text") else "input_value_mismatch",
        )
    if action_name == "select_dropdown" and deterministic:
        return ActionJudgement(
            data.get("selected") == params.get("option"),
            "selection_matched" if data.get("selected") == params.get("option") else "selection_mismatch",
        )
    if action_name == "scroll":
        return _truth(data.get("completed"), "scroll_not_completed")
    if action_name == "upload_file" and deterministic:
        return ActionJudgement(
            data.get("uploaded_asset_ref") == params.get("asset_ref"),
            "upload_matched" if data.get("uploaded_asset_ref") == params.get("asset_ref") else "upload_mismatch",
        )
    if action_name == "switch" and deterministic:
        if (
            params.get("page_registered") is not True
            or params.get("page_active") is not True
            or params.get("activation_fact") is not True
        ):
            return ActionJudgement(False, "switch_page_unregistered")
        return ActionJudgement(
            data.get("activated_page_ref") == params.get("page_ref"),
            "switch_matched" if data.get("activated_page_ref") == params.get("page_ref") else "switch_mismatch",
        )
    if action_name == "close" and deterministic:
        if params.get("page_closed") is not True or params.get("closure_fact") is not True:
            return ActionJudgement(False, "close_fact_missing")
        return ActionJudgement(
            data.get("closed_page_ref") == params.get("scope_page_ref"),
            "close_matched" if data.get("closed_page_ref") == params.get("scope_page_ref") else "close_not_completed",
        )
    if action_name in {"extract", "extract_variable"} and deterministic:
        declared_ref = params.get("declared_output_ref")
        variables = data.get("variables")
        valid = isinstance(declared_ref, str) and isinstance(variables, Mapping) and declared_ref in variables
        return ActionJudgement(valid, "extract_contract_met" if valid else "extract_output_missing")
    if action_name == "send_keys" and deterministic:
        return _truth(data.get("dispatched"), "keys_not_dispatched")
    declared_outputs = params.get("declared_output_refs")
    if isinstance(declared_outputs, list) and declared_outputs:
        variables = data.get("variables")
        valid = isinstance(variables, Mapping) and all(
            isinstance(ref, str) and ref in variables
            for ref in declared_outputs
        )
        return ActionJudgement(
            valid,
            "agent_outputs_met" if valid else "agent_output_missing",
        )
    completed = data.get("completed") is True or data.get("dispatched") is True
    return ActionJudgement(completed, "agent_action_completed" if completed else "agent_action_unconfirmed")


def _truth(value: object, failure: str) -> ActionJudgement:
    return ActionJudgement(value is True, "postcondition_met" if value is True else failure)
