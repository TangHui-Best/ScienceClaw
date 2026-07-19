from __future__ import annotations

from datetime import timedelta

import pytest

from rpa_agent.browser_use import (
    BrowserPageState,
    BrowserUseContextRequest,
    build_minimal_context,
)
from rpa_agent.creation import SkillCreationSession


def _session() -> SkillCreationSession:
    session = SkillCreationSession(
        session_id="session_context",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=8,
        fact_ttl=timedelta(seconds=30),
    )
    session.variables.write("采购订单.订单号", "PO-1001", producer_candidate_id="candidate_extract")
    session.variables.write("采购订单.供应商", "甲供应商", producer_candidate_id="candidate_extract")
    return session


def _request(**changes: object) -> BrowserUseContextRequest:
    values = {
        "current_instruction": "填写订单号并发起验收",
        "current_page_state": BrowserPageState(
            title="采购订单",
            url="https://system.test/orders",
            interactive_elements=("订单号", "发起验收"),
        ),
        "business_terms": ("采购订单", "验收登记"),
        "required_variable_refs": ("采购订单.订单号",),
        "allowed_inputs": {"acceptance_date": "登记日期"},
        "allowed_secret_names": ("erp_password",),
        "allowed_data_assets": {"attachment": "验收附件"},
        "page_aliases": {"main": "采购系统"},
    }
    values.update(changes)
    return BrowserUseContextRequest(**values)


def test_context_contains_only_current_instruction_and_selected_whitelist() -> None:
    context = build_minimal_context(_request(), variables=_session().variables)

    assert context == {
        "current_instruction": "填写订单号并发起验收",
        "current_page_state": {
            "title": "采购订单",
            "url": "https://system.test/orders",
            "interactive_elements": ["订单号", "发起验收"],
        },
        "business_terms": ["采购订单", "验收登记"],
        "variables": {"采购订单.订单号": "PO-1001"},
        "allowed_inputs": {"acceptance_date": "登记日期"},
        "allowed_secret_names": ["erp_password"],
        "allowed_data_assets": {"attachment": "验收附件"},
        "page_aliases": {"main": "采购系统"},
    }
    assert "采购订单.供应商" not in str(context)
    assert "session_context" not in str(context)


def test_context_is_copy_on_write_and_strongly_typed() -> None:
    elements = ["订单号"]
    request = _request(
        current_page_state=BrowserPageState(
            title="采购订单",
            url="https://system.test/orders",
            interactive_elements=tuple(elements),
        )
    )
    elements[0] = "被篡改"
    first = build_minimal_context(request, variables=_session().variables)
    first["current_page_state"]["interactive_elements"][0] = "再次篡改"
    second = build_minimal_context(request, variables=_session().variables)

    assert second["current_page_state"]["interactive_elements"][0] == "订单号"
    with pytest.raises(TypeError, match="browser_use_context.page_state_invalid"):
        _request(current_page_state={"title": "不允许任意映射"})


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("allowed_inputs", {"bad name": "用途"}, "name_invalid"),
        ("allowed_secret_names", ("bad name",), "name_invalid"),
        ("allowed_data_assets", {"attachment": "/tmp/private.csv"}, "unsafe_content"),
        ("page_aliases", {"runtime:tab:123": "采购系统"}, "name_invalid"),
    ],
)
def test_context_rejects_non_whitelisted_names_and_absolute_paths(
    field: str, value: object, error: str
) -> None:
    with pytest.raises((TypeError, ValueError), match=f"browser_use_context.{error}"):
        _request(**{field: value})


def test_context_missing_requested_variable_fails_closed() -> None:
    with pytest.raises(KeyError, match="session_variable_store.ref_missing"):
        build_minimal_context(
            _request(required_variable_refs=("采购订单.不存在",)),
            variables=_session().variables,
        )


@pytest.mark.parametrize(
    "unsafe",
    [r"C:\Users\tester\secret.txt", "/tmp/secret.txt", "token=abc", "Browser-use History"],
)
def test_context_final_filter_rejects_unsafe_variable_values(unsafe: str) -> None:
    session = _session()
    session.variables.write("采购订单.订单号", unsafe, producer_candidate_id="candidate_unsafe")
    with pytest.raises(ValueError, match="browser_use_context.unsafe_content"):
        build_minimal_context(_request(), variables=session.variables)
