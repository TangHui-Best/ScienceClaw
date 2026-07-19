from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter

from rpa_agent.contracts import (
    AcceptedSettlement,
    BrowserFact,
    BrowserScope,
    CoreTrace,
    TraceCandidate,
    validate_trace,
)
from rpa_agent.creation.page_registry import PageRegistry
from rpa_agent.creation.settlement import (
    SettlementAttempt,
    SettlementAttemptStatus,
    SettlementEngine,
)
from rpa_agent.creation.timeline import TimelineStore


NOW = datetime(2026, 7, 18, 1, 2, 3, tzinfo=timezone.utc)
FACT = TypeAdapter(BrowserFact)


def _scope(page_ref: str = "main") -> BrowserScope:
    return BrowserScope(page_ref=page_ref, frame_path=[])


def _candidate(
    *,
    candidate_id: str = "cand_click",
    ordinal: int = 7,
    status: str = "succeeded",
    action: dict | None = None,
    bindings: list[dict] | None = None,
) -> TraceCandidate:
    execution: dict = {
        "status": status,
        "started_at": NOW,
        "ended_at": None if status == "running" else NOW,
        "output": None,
        "error": None,
    }
    if status == "failed":
        execution["error"] = {"code": "tool_failed", "message": "Tool failed"}
    if status == "cancelled":
        execution["error"] = {"code": "cancelled", "message": "Cancelled"}
    return TraceCandidate.model_validate(
        {
            "candidate_id": candidate_id,
            "ordinal": ordinal,
            "origin": "human",
            "scope_hint": {"page_ref": None, "frame_path": None},
            "action_hint": action or {
                "kind": "click",
                "target_hint": {
                    "name": "查询",
                    "locators": [{"strategy": "role", "role": "button", "name": "查询"}],
                },
                "button": "left",
                "count": 1,
            },
            "binding_hints": bindings or [],
            "execution": execution,
        }
    )


def _fact(
    *,
    fact_id: str,
    order: int,
    candidate_id: str | None,
    kind: str,
    runtime_page: str = "runtime_main",
    detail: dict | None = None,
):
    payload = {
        "fact_id": fact_id,
        "observed_order": order,
        "kind": kind,
        "candidate_id": candidate_id,
        "observed_at": NOW,
        "runtime_scope": {"page_runtime_ref": runtime_page},
    }
    if detail is not None:
        payload["detail"] = detail
    return FACT.validate_python(payload)


def test_success_is_necessary_but_target_and_scope_are_still_required() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    missing_target = _candidate(
        action={"kind": "press", "target_hint": None},
        bindings=[{
            "name": "keys", "direction": "input", "kind_hint": "literal",
            "value": "Enter", "sensitive": False,
        }],
    )

    unresolved_scope = engine.settle(missing_target, facts=(), scope=None)
    assert unresolved_scope.status == "rejected"
    assert unresolved_scope.diagnostic.code == "scope_unresolved"

    unresolved_target = engine.settle(missing_target, facts=(), scope=_scope())
    assert unresolved_target.status == "rejected"
    assert unresolved_target.diagnostic.code == "target_unresolved"
    assert not hasattr(unresolved_target, "core_trace")


def test_scope_must_be_registered_and_open() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    unknown = engine.settle(_candidate(), facts=(), scope=_scope("page_999"))
    assert unknown.status == "rejected"
    assert unknown.diagnostic.code == "scope_unresolved"

    popup = _fact(
        fact_id="fact_popup", order=1, candidate_id=None, kind="new_page",
        runtime_page="runtime_popup", detail={"initial_url": "about:blank"},
    )
    closed = _fact(
        fact_id="fact_closed", order=2, candidate_id=None, kind="page_closed",
        runtime_page="runtime_popup",
    )
    pages.apply(popup)
    pages.apply(closed)
    result = engine.settle(_candidate(), facts=(), scope=_scope("page_001"))
    assert result.status == "rejected"
    assert result.diagnostic.code == "scope_unresolved"


def test_close_page_accepts_registered_page_after_closed_fact_is_applied() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    popup = _fact(
        fact_id="fact_popup", order=1, candidate_id=None, kind="new_page",
        runtime_page="runtime_popup", detail={"initial_url": "about:blank"},
    )
    closed = _fact(
        fact_id="fact_closed", order=2, candidate_id="cand_close", kind="page_closed",
        runtime_page="runtime_popup",
    )
    pages.apply(popup)
    pages.apply(closed)
    candidate = _candidate(
        candidate_id="cand_close", action={"kind": "close_page"}
    )

    result = engine.settle(candidate, facts=(closed,), scope=_scope("page_001"))

    assert result.status == "accepted"
    assert result.core_trace.action.kind == "close_page"


def test_close_page_rejects_unknown_open_and_wrong_closed_page() -> None:
    unknown_pages = PageRegistry(main_runtime_ref="runtime_main")
    unknown = SettlementEngine(unknown_pages).settle(
        _candidate(candidate_id="cand_close", action={"kind": "close_page"}),
        facts=(),
        scope=_scope("page_999"),
    )
    assert unknown.status == "rejected"
    assert unknown.diagnostic.code == "scope_unresolved"

    pages = PageRegistry(main_runtime_ref="runtime_main")
    popup_one = _fact(
        fact_id="fact_popup_one", order=1, candidate_id=None, kind="new_page",
        runtime_page="runtime_one", detail={"initial_url": "about:blank"},
    )
    popup_two = _fact(
        fact_id="fact_popup_two", order=2, candidate_id=None, kind="new_page",
        runtime_page="runtime_two", detail={"initial_url": "about:blank"},
    )
    pages.apply(popup_one)
    pages.apply(popup_two)
    candidate = _candidate(candidate_id="cand_close", action={"kind": "close_page"})
    still_open = SettlementEngine(pages).settle(
        candidate, facts=(), scope=_scope("page_001")
    )
    assert still_open.status == "rejected"
    assert still_open.diagnostic.code == "scope_unresolved"

    close_one = _fact(
        fact_id="fact_close_one", order=3, candidate_id=None, kind="page_closed",
        runtime_page="runtime_one",
    )
    close_two = _fact(
        fact_id="fact_close_two", order=4, candidate_id="cand_close", kind="page_closed",
        runtime_page="runtime_two",
    )
    pages.apply(close_one)
    pages.apply(close_two)
    wrong = SettlementEngine(pages).settle(
        candidate, facts=(close_two,), scope=_scope("page_001")
    )
    assert wrong.status == "rejected"
    assert wrong.diagnostic.code == "scope_unresolved"


def test_failed_close_page_can_normalize_to_agent_on_closed_scope() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    popup = _fact(
        fact_id="fact_popup", order=1, candidate_id=None, kind="new_page",
        runtime_page="runtime_popup", detail={"initial_url": "about:blank"},
    )
    closed = _fact(
        fact_id="fact_closed", order=2, candidate_id="cand_close", kind="page_closed",
        runtime_page="runtime_popup",
    )
    pages.apply(popup)
    pages.apply(closed)
    original = _candidate(
        candidate_id="cand_close", status="failed", action={"kind": "close_page"}
    )

    attempt = engine.settle(
        original, facts=(closed,), scope=_scope("page_001")
    )
    assert attempt.status is SettlementAttemptStatus.NEEDS_CONFIRMATION
    normalized = engine.confirm_agent_fallback(
        original,
        facts=(closed,),
        scope=_scope("page_001"),
        instruction="关闭当前业务页面",
        confirmed_at=NOW,
    )
    assert normalized.execution.status == "succeeded"
    assert normalized.action_hint.kind == "agent"

    accepted = engine.settle(
        normalized, facts=(closed,), scope=_scope("page_001")
    )
    assert accepted.status == "accepted"
    assert accepted.core_trace.action.kind == "agent"
    assert accepted.core_trace.effects == []


def test_closed_scope_agent_requires_one_matching_page_closed_fact() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    popup_one = _fact(
        fact_id="fact_popup_one", order=1, candidate_id=None, kind="new_page",
        runtime_page="runtime_one", detail={"initial_url": "about:blank"},
    )
    popup_two = _fact(
        fact_id="fact_popup_two", order=2, candidate_id=None, kind="new_page",
        runtime_page="runtime_two", detail={"initial_url": "about:blank"},
    )
    close_one = _fact(
        fact_id="fact_close_one", order=3, candidate_id="cand_close", kind="page_closed",
        runtime_page="runtime_one",
    )
    close_two = _fact(
        fact_id="fact_close_two", order=4, candidate_id="cand_close", kind="page_closed",
        runtime_page="runtime_two",
    )
    for fact in (popup_one, popup_two, close_one, close_two):
        pages.apply(fact)
    original = _candidate(
        candidate_id="cand_close", status="failed", action={"kind": "close_page"}
    )
    normalized = engine.confirm_agent_fallback(
        original,
        facts=(close_one,),
        scope=_scope("page_001"),
        instruction="关闭当前业务页面",
        confirmed_at=NOW,
    )

    for facts in ((), (close_two,), (close_one, close_two)):
        result = engine.settle(
            normalized, facts=facts, scope=_scope("page_001")
        )
        assert result.status == "rejected"
        assert result.diagnostic.code in {"scope_unresolved", "browser_fact_unresolved"}


def test_accepted_trace_is_complete_deterministic_and_sequence_equals_ordinal() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    candidate = _candidate(candidate_id="cand_repeatable", ordinal=30)

    first = engine.settle(candidate, facts=(), scope=_scope())
    second = engine.settle(candidate, facts=(), scope=_scope())

    assert first.status == second.status == "accepted"
    assert first.core_trace == second.core_trace
    assert first.core_trace.sequence == 30
    assert first.core_trace.trace_id.startswith("trace_")
    assert not hasattr(first, "diagnostic")


def test_null_candidate_fact_updates_page_registry_but_creates_no_effect() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    lifecycle = _fact(
        fact_id="fact_popup",
        order=1,
        candidate_id=None,
        kind="new_page",
        runtime_page="runtime_popup",
        detail={"initial_url": "about:blank"},
    )
    pages.apply(lifecycle)

    result = engine.settle(_candidate(), facts=(lifecycle,), scope=_scope())
    assert result.status == "accepted"
    assert result.core_trace.effects == []
    assert pages.resolve("runtime_popup") == "page_001"


def test_foreign_fact_is_rejected_with_formal_diagnostic() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    foreign = _fact(
        fact_id="fact_foreign", order=1, candidate_id="cand_other", kind="navigation",
        detail={
            "frame_runtime_ref": "frame_main", "is_main_frame": True,
            "url": "https://example.test/other",
        },
    )

    result = engine.settle(_candidate(), facts=(foreign,), scope=_scope())

    assert result.status == "rejected"
    assert result.diagnostic.code == "browser_fact_unresolved"
    assert "fact_foreign" not in result.diagnostic.message


def test_new_page_and_completed_download_are_the_only_allowed_compound_effect() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    new_page = _fact(
        fact_id="fact_popup", order=1, candidate_id="cand_export", kind="new_page",
        runtime_page="runtime_popup", detail={"initial_url": "about:blank"},
    )
    download = _fact(
        fact_id="fact_download", order=2, candidate_id="cand_export", kind="download",
        detail={
            "download_ref": "runtime_download", "suggested_filename": "orders.xlsx",
            "status": "completed", "failure_reason": None,
        },
    )
    pages.apply(new_page)
    candidate = _candidate(
        candidate_id="cand_export",
        bindings=[{
            "name": "downloaded_file", "direction": "output", "kind_hint": "data_asset",
            "ref_hint": "orders_file", "sensitive": False,
        }],
    )

    accepted = engine.settle(
        candidate,
        facts=(new_page, download),
        scope=_scope(),
        resolved_assets={"runtime_download": "orders_file"},
    )

    assert accepted.status == "accepted"
    assert [effect.kind for effect in accepted.core_trace.effects] == ["new_page", "download"]
    assert accepted.core_trace.effects[0].page_ref == "page_001"


def test_new_page_initial_navigation_is_not_a_source_navigation_effect() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    popup = _fact(
        fact_id="fact_popup", order=1, candidate_id="cand_popup", kind="new_page",
        runtime_page="runtime_popup", detail={"initial_url": "about:blank"},
    )
    initial_navigation = _fact(
        fact_id="fact_initial_nav", order=2, candidate_id="cand_popup", kind="navigation",
        runtime_page="runtime_popup", detail={
            "frame_runtime_ref": "popup_main", "is_main_frame": True,
            "url": "https://example.test/random?token=opaque",
        },
    )
    pages.apply(popup)
    pages.apply(initial_navigation)

    result = engine.settle(
        _candidate(candidate_id="cand_popup"),
        facts=(popup, initial_navigation),
        scope=_scope(),
    )
    assert result.status == "accepted"
    assert [effect.kind for effect in result.core_trace.effects] == ["new_page"]


def test_new_page_download_and_initial_navigation_keep_allowed_compound_effect() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    popup = _fact(
        fact_id="fact_popup", order=1, candidate_id="cand_export", kind="new_page",
        runtime_page="runtime_popup", detail={"initial_url": "about:blank"},
    )
    initial_navigation = _fact(
        fact_id="fact_initial_nav", order=2, candidate_id="cand_export", kind="navigation",
        runtime_page="runtime_popup", detail={
            "frame_runtime_ref": "popup_main", "is_main_frame": True,
            "url": "https://example.test/random",
        },
    )
    download = _fact(
        fact_id="fact_download", order=3, candidate_id="cand_export", kind="download",
        detail={
            "download_ref": "runtime_download", "suggested_filename": "orders.xlsx",
            "status": "completed", "failure_reason": None,
        },
    )
    pages.apply(popup)
    pages.apply(initial_navigation)
    candidate = _candidate(
        candidate_id="cand_export",
        bindings=[{
            "name": "downloaded_file", "direction": "output", "kind_hint": "data_asset",
            "ref_hint": "orders_file", "sensitive": False,
        }],
    )
    result = engine.settle(
        candidate,
        facts=(popup, initial_navigation, download),
        scope=_scope(),
        resolved_assets={"runtime_download": "orders_file"},
    )
    assert result.status == "accepted"
    assert [effect.kind for effect in result.core_trace.effects] == ["new_page", "download"]


def test_failed_download_never_forms_effect() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    failed = _fact(
        fact_id="fact_download", order=1, candidate_id="cand_export", kind="download",
        detail={
            "download_ref": "runtime_download", "suggested_filename": None,
            "status": "failed", "failure_reason": "network",
        },
    )
    candidate = _candidate(candidate_id="cand_export")

    result = engine.settle(candidate, facts=(failed,), scope=_scope())

    assert result.status == "rejected"
    assert result.diagnostic.code in {"asset_unavailable", "browser_fact_unresolved"}
    assert not hasattr(result, "core_trace")


def test_navigation_collapses_redirects_and_navigate_does_not_duplicate_effect() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    redirects = tuple(
        _fact(
            fact_id=f"fact_nav_{order}", order=order, candidate_id="cand_nav",
            kind="navigation", detail={
                "frame_runtime_ref": "frame_main", "is_main_frame": True,
                "url": f"https://example.test/{order}",
            },
        )
        for order in (1, 2)
    )
    click = engine.settle(
        _candidate(candidate_id="cand_nav"), facts=redirects, scope=_scope()
    )
    assert [effect.kind for effect in click.core_trace.effects] == ["navigation"]

    navigate = _candidate(
        candidate_id="cand_go",
        action={"kind": "navigate", "mode": "url"},
        bindings=[{
            "name": "url", "direction": "input", "kind_hint": "skill_input",
            "ref_hint": "orders_url", "sensitive": False,
        }],
    )
    navigate_fact = redirects[0].model_copy(update={"candidate_id": "cand_go"})
    result = engine.settle(navigate, facts=(navigate_fact,), scope=_scope())
    assert result.status == "accepted"
    assert result.core_trace.effects == []


def test_dialog_compound_or_duplicate_effects_are_rejected() -> None:
    pages = PageRegistry(main_runtime_ref="runtime_main")
    engine = SettlementEngine(pages)
    popup = _fact(
        fact_id="fact_popup", order=1, candidate_id="cand_click", kind="new_page",
        runtime_page="runtime_popup", detail={"initial_url": "about:blank"},
    )
    dialog = _fact(
        fact_id="fact_dialog", order=2, candidate_id="cand_click", kind="dialog",
        detail={
            "dialog_type": "confirm", "response": "accept", "prompt_value": None,
        },
    )
    pages.apply(popup)

    result = engine.settle(_candidate(), facts=(popup, dialog), scope=_scope())
    assert result.status == "rejected"
    assert result.diagnostic.code == "browser_fact_unresolved"


def test_prompt_plaintext_cannot_be_copied_into_core_trace() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    prompt = _fact(
        fact_id="fact_prompt", order=1, candidate_id="cand_prompt", kind="dialog",
        detail={
            "dialog_type": "prompt", "response": "accept", "prompt_value": "sensitive",
        },
    )
    candidate = _candidate(
        candidate_id="cand_prompt",
        bindings=[{
            "name": "dialog_input", "direction": "input", "kind_hint": "literal",
            "value": "sensitive", "sensitive": True,
        }],
    )

    result = engine.settle(candidate, facts=(prompt,), scope=_scope())

    assert result.status == "rejected"
    assert result.diagnostic.code == "binding_unresolved"
    assert "sensitive" not in result.diagnostic.message


def test_empty_prompt_requires_no_input_binding() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    prompt = _fact(
        fact_id="fact_prompt", order=1, candidate_id="cand_prompt", kind="dialog",
        detail={"dialog_type": "prompt", "response": "accept", "prompt_value": None},
    )
    result = engine.settle(
        _candidate(candidate_id="cand_prompt"), facts=(prompt,), scope=_scope()
    )
    assert result.status == "accepted"
    assert result.core_trace.effects[0].input_binding is None


@pytest.mark.parametrize(
    ("binding", "expected_kind"),
    [
        ({
            "name": "dialog_value", "direction": "input", "kind_hint": "literal",
            "value": "hello", "sensitive": False,
        }, "literal"),
        ({
            "name": "dialog_value", "direction": "input", "kind_hint": "secret",
            "ref_hint": "dialog_secret", "sensitive": True,
        }, "secret"),
    ],
)
def test_prompt_maps_one_structurally_applicable_binding(binding: dict, expected_kind: str) -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    prompt = _fact(
        fact_id="fact_prompt", order=1, candidate_id="cand_prompt", kind="dialog",
        detail={"dialog_type": "prompt", "response": "accept", "prompt_value": "value"},
    )
    result = engine.settle(
        _candidate(candidate_id="cand_prompt", bindings=[binding]),
        facts=(prompt,),
        scope=_scope(),
    )
    assert result.status == "accepted"
    assert result.core_trace.effects[0].input_binding == "dialog_value"
    assert result.core_trace.data_bindings[0].kind == expected_kind


def test_prompt_multiple_applicable_bindings_are_rejected() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    prompt = _fact(
        fact_id="fact_prompt", order=1, candidate_id="cand_prompt", kind="dialog",
        detail={"dialog_type": "prompt", "response": "accept", "prompt_value": "value"},
    )
    bindings = [
        {"name": name, "direction": "input", "kind_hint": "literal", "value": value,
         "sensitive": False}
        for name, value in (("dialog_one", "one"), ("dialog_two", "two"))
    ]
    result = engine.settle(
        _candidate(candidate_id="cand_prompt", bindings=bindings),
        facts=(prompt,),
        scope=_scope(),
    )
    assert result.status == "rejected"
    assert result.diagnostic.code == "binding_unresolved"


def test_failed_without_side_effect_is_rejected_but_side_effect_is_retained_for_confirmation() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    ordinary_failure = engine.settle(
        _candidate(status="failed"), facts=(), scope=_scope()
    )
    assert ordinary_failure.status == "rejected"
    assert ordinary_failure.diagnostic.code == "execution_failed"

    navigation = _fact(
        fact_id="fact_nav", order=1, candidate_id="cand_click", kind="navigation",
        detail={
            "frame_runtime_ref": "frame_main", "is_main_frame": True,
            "url": "https://example.test/result",
        },
    )
    pending = engine.settle(
        _candidate(status="failed"), facts=(navigation,), scope=_scope()
    )
    assert isinstance(pending, SettlementAttempt)
    assert pending.status is SettlementAttemptStatus.NEEDS_CONFIRMATION
    assert pending.candidate_id == "cand_click"

    original = _candidate(status="failed")
    normalized = engine.confirm_agent_fallback(
        original,
        facts=(navigation,),
        scope=_scope(),
        instruction="点击查询并进入结果页",
        confirmed_at=NOW,
    )
    assert original.execution.status == "failed"
    assert normalized is not original
    assert normalized.execution.status == "succeeded"
    assert normalized.action_hint.kind == "agent"
    confirmed = engine.settle(normalized, facts=(navigation,), scope=_scope())
    assert confirmed.status == "accepted"
    assert confirmed.core_trace.action.kind == "agent"
    assert [effect.kind for effect in confirmed.core_trace.effects] == ["navigation"]


def test_running_candidate_produces_no_settlement_result() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    attempt = engine.settle(_candidate(status="running"), facts=(), scope=_scope())
    assert isinstance(attempt, SettlementAttempt)
    assert attempt.status is SettlementAttemptStatus.WAITING


def test_running_with_side_effect_needs_confirmation() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    navigation = _fact(
        fact_id="fact_nav", order=1, candidate_id="cand_click", kind="navigation",
        detail={
            "frame_runtime_ref": "frame_main", "is_main_frame": True,
            "url": "https://example.test/result",
        },
    )
    attempt = engine.settle(
        _candidate(status="running"), facts=(navigation,), scope=_scope()
    )
    assert attempt.status is SettlementAttemptStatus.NEEDS_CONFIRMATION

    original = _candidate(status="running")
    normalized = engine.confirm_agent_fallback(
        original,
        facts=(navigation,),
        scope=_scope(),
        instruction="点击查询并进入结果页",
        confirmed_at=NOW,
    )
    assert original.execution.status == "running"
    assert normalized.execution.status == "succeeded"
    accepted = engine.settle(normalized, facts=(navigation,), scope=_scope())
    assert accepted.status == "accepted"


def test_confirmation_time_cannot_precede_failed_execution_end() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    original = _candidate(status="failed")
    candidate = original.model_copy(update={
        "execution": original.execution.model_copy(
            update={"ended_at": NOW.replace(second=10)}
        )
    })
    navigation = _fact(
        fact_id="fact_nav", order=1, candidate_id="cand_click", kind="navigation",
        detail={
            "frame_runtime_ref": "frame_main", "is_main_frame": True,
            "url": "https://example.test/result",
        },
    )

    with pytest.raises(ValueError, match="settlement.agent_fallback_time_regressed"):
        engine.confirm_agent_fallback(
            candidate,
            facts=(navigation,),
            scope=_scope(),
            instruction="点击查询并进入结果页",
            confirmed_at=NOW,
        )


def test_confirmation_time_timezone_mismatch_has_stable_error() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    original = _candidate(status="failed")
    candidate = original.model_copy(update={
        "execution": original.execution.model_copy(
            update={"ended_at": datetime(2026, 7, 18, 1, 2, 10)}
        )
    })
    navigation = _fact(
        fact_id="fact_nav", order=1, candidate_id="cand_click", kind="navigation",
        detail={
            "frame_runtime_ref": "frame_main", "is_main_frame": True,
            "url": "https://example.test/result",
        },
    )

    with pytest.raises(ValueError, match="settlement.agent_fallback_time_incomparable"):
        engine.confirm_agent_fallback(
            candidate,
            facts=(navigation,),
            scope=_scope(),
            instruction="点击查询并进入结果页",
            confirmed_at=NOW.replace(second=2),
        )


def test_page_registry_resolution_failure_is_not_misreported_as_binding() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    activation = _fact(
        fact_id="fact_activation", order=1, candidate_id="cand_switch",
        kind="page_activated", runtime_page="runtime_unknown",
    )
    candidate = _candidate(
        candidate_id="cand_switch",
        action={"kind": "switch_page", "page_ref": "page_001"},
    )

    result = engine.settle(candidate, facts=(activation,), scope=_scope())

    assert result.status == "rejected"
    assert result.diagnostic.code == "scope_unresolved"


def test_later_candidate_settles_without_waiting_for_earlier_pending() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    earlier = engine.settle(
        _candidate(candidate_id="cand_pending", ordinal=10, status="running"),
        facts=(), scope=_scope(),
    )
    later = engine.settle(
        _candidate(candidate_id="cand_later", ordinal=30), facts=(), scope=_scope()
    )
    assert isinstance(earlier, SettlementAttempt)
    assert later.status == "accepted"
    assert later.core_trace.sequence == 30


def test_timeline_store_accepts_only_accepted_and_is_idempotent() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    store = TimelineStore()
    accepted = engine.settle(_candidate(), facts=(), scope=_scope())
    rejected = engine.settle(_candidate(status="failed"), facts=(), scope=_scope())

    assert store.append(accepted) is True
    assert store.append(accepted) is False
    with pytest.raises(ValueError, match="timeline_store.accepted_required"):
        store.append(rejected)
    timeline = store.timeline()
    assert [trace.sequence for trace in timeline.traces] == [7]


def test_timeline_store_rejects_same_id_conflict_and_sequence_conflict() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    first = engine.settle(
        _candidate(candidate_id="cand_first", ordinal=7), facts=(), scope=_scope()
    )
    store = TimelineStore()
    store.append(first)

    changed_same_id = first.model_copy(
        update={"core_trace": first.core_trace.model_copy(update={"sequence": 8})}
    )
    with pytest.raises(ValueError, match="timeline_store.trace_id_conflict"):
        store.append(changed_same_id)

    same_sequence = engine.settle(
        _candidate(candidate_id="cand_second", ordinal=7), facts=(), scope=_scope()
    )
    with pytest.raises(ValueError, match="timeline_store.sequence_conflict"):
        store.append(same_sequence)


def test_timeline_store_validates_single_trace_before_mutating_state() -> None:
    assert callable(validate_trace)
    invalid_trace = CoreTrace.model_validate({
        "trace_id": "trace_invalid",
        "sequence": 1,
        "scope": {"page_ref": "main", "frame_path": []},
        "action": {
            "kind": "fill",
            "target": {
                "name": "订单号",
                "locators": [{"strategy": "label", "value": "订单号"}],
            },
        },
        "data_bindings": [],
        "effects": [],
    })
    invalid = AcceptedSettlement(
        candidate_id="cand_invalid", status="accepted", core_trace=invalid_trace
    )
    store = TimelineStore()

    with pytest.raises(ValueError, match="binding.required"):
        store.append(invalid)

    assert store.timeline().traces == []


def test_timeline_store_copies_on_append_and_on_read() -> None:
    engine = SettlementEngine(PageRegistry(main_runtime_ref="runtime_main"))
    accepted = engine.settle(_candidate(), facts=(), scope=_scope())
    store = TimelineStore()
    store.append(accepted)

    accepted.core_trace.effects.append({"kind": "navigation"})
    accepted.core_trace.data_bindings.append({"kind": "invalid"})
    first_read = store.timeline()
    assert first_read.traces[0].effects == []
    assert first_read.traces[0].data_bindings == []

    first_read.traces[0].effects.append({"kind": "navigation"})
    first_read.traces.append(first_read.traces[0])
    second_read = store.timeline()
    assert len(second_read.traces) == 1
    assert second_read.traces[0].effects == []


def test_timeline_store_rejects_constructed_pollution_before_mutating() -> None:
    forged_trace = CoreTrace.model_construct(
        trace_id="trace_forged",
        sequence=1,
        scope={"page_ref": "main", "frame_path": []},
        action={"kind": "click"},
        data_bindings=[],
        effects=[{"kind": "not_an_effect"}],
    )
    forged = AcceptedSettlement.model_construct(
        candidate_id="cand_forged", status="accepted", core_trace=forged_trace
    )
    store = TimelineStore()

    with pytest.raises(ValueError):
        store.append(forged)

    assert store.timeline().traces == []
