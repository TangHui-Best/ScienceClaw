from backend.rpa.trace_models import RPAAcceptedTrace, RPAAIExecution, RPATraceType, RPARuntimeResults
import backend.rpa.trace_recorder as trace_recorder
from backend.rpa.trace_recorder import infer_dataflow_for_fill, manual_step_to_trace


def test_manual_navigation_step_becomes_navigation_trace():
    trace = manual_step_to_trace(
        {
            "id": "step-1",
            "action": "navigate",
            "source": "record",
            "description": "Open GitHub Trending",
            "url": "https://github.com/trending",
            "target": "https://github.com/trending",
        }
    )

    assert trace.trace_type == "navigation"
    assert trace.source == "manual"
    assert trace.after_page.url == "https://github.com/trending"


def test_manual_fill_step_records_value_and_locator_candidates():
    trace = manual_step_to_trace(
        {
            "id": "step-2",
            "action": "fill",
            "source": "record",
            "description": "Fill customer name",
            "target": '{"method":"role","role":"textbox","name":"Customer Name"}',
            "value": "Alice Zhang",
            "locator_candidates": [{"kind": "role", "locator": {"method": "role", "role": "textbox"}}],
        }
    )

    assert trace.trace_type == "manual_action"
    assert trace.value == "Alice Zhang"
    assert trace.locator_candidates[0]["kind"] == "role"


def test_extract_text_step_becomes_data_capture_trace():
    trace = manual_step_to_trace(
        {
            "id": "step-3",
            "action": "extract_text",
            "result_key": "latest_issue_title",
            "output": "Fix the parser",
        }
    )

    assert trace.trace_type == "data_capture"
    assert trace.output_key == "latest_issue_title"


def test_manual_step_to_trace_preserves_tab_transition_signal():
    trace = manual_step_to_trace(
        {
            "id": "switch-1",
            "action": "switch_tab",
            "source": "record",
            "description": "切换到标签页 iSales+",
            "tab_id": "tab-root",
            "source_tab_id": "tab-root",
            "target_tab_id": "tab-sales",
        }
    )

    assert trace.signals["tab"] == {
        "tab_id": "tab-root",
        "source_tab_id": "tab-root",
        "target_tab_id": "tab-sales",
    }


def test_fill_trace_links_literal_value_to_runtime_result_ref():
    runtime_results = RPARuntimeResults(values={"customer_info": {"name": "Alice Zhang"}})
    trace = manual_step_to_trace(
        {
            "id": "fill-1",
            "action": "fill",
            "source": "record",
            "description": "Fill customer name",
            "value": "Alice Zhang",
        }
    )

    updated = infer_dataflow_for_fill(trace, runtime_results)

    assert updated.trace_type == "dataflow_fill"
    assert updated.dataflow.selected_source_ref == "customer_info.name"


def test_ai_fill_trace_links_verified_filled_value_to_runtime_result_ref():
    runtime_results = RPARuntimeResults(values={"page_title": "Quarterly Report"})
    trace = RPAAcceptedTrace(
        trace_type=RPATraceType.AI_OPERATION,
        source="ai",
        user_instruction="将提到的标题填入到当前页面的PR 概要输入框",
        description="Fill PR summary",
        output={
            "action_performed": True,
            "action_type": "fill",
            "filled_value": "Quarterly Report",
            "target": "PR概要",
        },
        ai_execution=RPAAIExecution(
            code=(
                "async def run(page, results):\n"
                "    value = results['page_title']\n"
                "    await page.get_by_placeholder('请输入PR概要').fill(value)\n"
                "    return {'action_performed': True, 'action_type': 'fill', 'filled_value': value}"
            )
        ),
        locator_candidates=[
            {
                "locator": {"method": "placeholder", "value": "请输入PR概要"},
                "selected": True,
            }
        ],
    )

    updated = trace_recorder.infer_dataflow_for_ai_fill(trace, runtime_results)

    assert updated.trace_type == "dataflow_fill"
    assert updated.dataflow.selected_source_ref == "page_title"
    assert updated.dataflow.value == "Quarterly Report"
    assert updated.action == "fill"


def test_manual_step_to_trace_preserves_signals_and_filters_invalid_locators():
    trace = manual_step_to_trace(
        {
            "id": "step-4",
            "action": "fill",
            "source": "record",
            "description": "Fill account",
            "target": '{"selected": true}',
            "locator_candidates": [
                {"selected": True},
                {"locator": {"method": "css", "value": ""}},
                {"locator": {"method": "role", "role": "textbox", "name": "Account"}, "selected": False},
            ],
            "validation": {"status": "broken", "details": "missing locator"},
            "signals": {"navigation": {"url": "https://example.com/next"}},
        }
    )

    assert trace.validation["status"] == "broken"
    assert trace.signals["navigation"]["url"] == "https://example.com/next"
    assert trace.locator_candidates == [
        {"locator": {"method": "role", "role": "textbox", "name": "Account"}, "selected": True}
    ]

