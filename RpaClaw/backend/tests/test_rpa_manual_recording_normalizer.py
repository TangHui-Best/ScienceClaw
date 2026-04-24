from backend.rpa.manual_recording_normalizer import (
    build_manual_recording_outcome,
    normalize_manual_candidate,
)


def test_normalize_playwright_locator_first_into_nth_role_locator():
    normalized = normalize_manual_candidate(
        {
            "kind": "role",
            "playwright_locator": 'page.get_by_role("textbox").first',
            "selected": True,
        }
    )
    assert normalized["locator"] == {
        "method": "nth",
        "locator": {"method": "role", "role": "textbox"},
        "index": 0,
    }


def test_build_outcome_accepts_canonicalized_interactive_action():
    outcome = build_manual_recording_outcome(
        action="click",
        description='点击 textbox("Search")',
        target="",
        locator_candidates=[
            {
                "kind": "role",
                "playwright_locator": 'page.get_by_role("textbox").first',
                "selected": True,
            }
        ],
        validation={"status": "ok"},
    )
    assert outcome.accepted_action is not None
    assert outcome.diagnostic is None
    assert outcome.accepted_action.target == {
        "method": "nth",
        "locator": {"method": "role", "role": "textbox"},
        "index": 0,
    }


def test_build_outcome_routes_missing_canonical_target_to_diagnostic():
    outcome = build_manual_recording_outcome(
        action="fill",
        description='输入 "foo" 到 None',
        target="",
        locator_candidates=[{"playwright_locator": 'page.locator(".mystery")'}],
        validation={"status": "ok"},
        value="foo",
    )
    assert outcome.accepted_action is None
    assert outcome.diagnostic is not None
    assert outcome.diagnostic.failure_reason == "canonical_target_missing"
