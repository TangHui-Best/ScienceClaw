from __future__ import annotations

import asyncio
import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest
from rpa_agent.browser_use import (
    ActualToolAction,
    BrowserUseRecordingAdapter,
    TargetResolution,
)
from rpa_agent.compiler import DeterministicCompiler
from rpa_agent.configuration import SkillConfigurationDraft, transform_configuration
from rpa_agent.contracts import BrowserScope
from rpa_agent.creation import (
    ControlMode,
    InteractionKind,
    ManualEvent,
    ManualEventKind,
    SkillCreationSession,
)


NOW = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)


def test_creation_chain_reaches_compiler_without_handwritten_coretrace(
    tmp_path: Path,
) -> None:
    session = SkillCreationSession(
        session_id="first_e2e_probe",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=32,
        fact_ttl=timedelta(minutes=1),
    )
    reservation = session.reserve_manual(
        candidate_id="manual_query_click",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="main_frame",
    )
    session.ingest_manual(
        reservation,
        ManualEvent(
            kind=ManualEventKind.CLICK,
            page_runtime_ref="runtime_main",
            frame_runtime_ref="main_frame",
            target_key="query-orders",
            target_name="Query orders",
            target_locators=(
                {"strategy": "role", "role": "button", "name": "Query", "exact": True},
                {"strategy": "test_id", "value": "query-orders"},
            ),
            interaction_kind=InteractionKind.CLICK,
            observed_at=NOW,
        ),
    )
    session.switch_control(ControlMode.AGENT, at=NOW + timedelta(seconds=1))

    extracted = {
        "purchase_order": {
            "order_no": "recording-sample-only",
            "supplier": "recording-supplier-only",
        }
    }

    async def executor(_action: ActualToolAction) -> dict[str, object]:
        return {"success": True}

    async def evidence(_action: ActualToolAction, _result: object) -> dict[str, object]:
        return {"variables": extracted}

    async def resolve(action: ActualToolAction) -> TargetResolution:
        return TargetResolution(target_hint=action.target_hint, match_count=1)

    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=executor,
        evidence_provider=evidence,
        target_resolver=resolve,
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW + timedelta(seconds=2),
    )
    report = asyncio.run(
        adapter.record_round(
            [
                ActualToolAction(
                    action_name="extract",
                    candidate_id="browser_use_extract_order",
                    params={"mode": "text"},
                    business_intent="Extract the matching purchase order",
                    runtime_page_ref="runtime_main",
                    runtime_frame_ref="main_frame",
                    page_ref="main",
                    frame_path=(),
                    target_hint={
                        "name": "Order result table",
                        "locators": (
                            {"strategy": "test_id", "value": "order-results-table"},
                        ),
                    },
                    binding_hints=(
                        {
                            "name": "result",
                            "direction": "output",
                            "kind_hint": "variable",
                            "ref_hint": "purchase_order",
                            "sensitive": False,
                        },
                    ),
                )
            ]
        )
    )

    for candidate_id in session.candidates:
        outcome = session.settle_candidate(
            candidate_id,
            scope=BrowserScope(page_ref="main", frame_path=[]),
        )
        assert outcome.status == "accepted"

    readiness = session.build_readiness()
    assert readiness.ready, readiness.issues
    assert {candidate.origin for candidate in session.candidates.values()} == {
        "human",
        "agent",
    }
    assert report.actual_action_count == 1
    assert report.candidate_ids == ("browser_use_extract_order",)
    assert not readiness.issues

    configured = transform_configuration(
        readiness,
        SkillConfigurationDraft.model_validate(
            {
                "schema_version": "skill-configuration-draft/v0.1",
                "skill": {
                    "name": "Purchase order acceptance",
                    "description": "First vertical creation-chain feasibility probe.",
                },
                "inputs": [],
                "secrets": [],
                "asset_inputs": [],
                "outputs": [
                    {
                        "name": "purchase_order_result",
                        "title": "Purchase order",
                        "variable_ref": "purchase_order",
                        "value_type": "json",
                    }
                ],
                "asset_outputs": [],
                "binding_promotions": [],
                "stage_2_rules": None,
            }
        ),
        skill_id="first-vertical-probe",
    )
    destination = tmp_path / "generated-skill"
    result = DeterministicCompiler().compile(
        configured.timeline,
        configured.skill_definition,
        destination,
    )

    assert result.status == "published", result.issues
    assert result.artifacts is not None
    assert set(result.artifacts.files) == {
        "SKILL.md",
        "skill.manifest.json",
        "skill.py",
        "browser_segment.py",
    }
    assert len(configured.timeline.traces) == 2


def test_same_compiled_artifact_replays_profiles_a_and_b_with_isolated_oracles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from live_first_skill_replay import run_offline_replay

    compile_calls = 0
    original_compile = DeterministicCompiler.compile

    def counted_compile(self, *args, **kwargs):
        nonlocal compile_calls
        compile_calls += 1
        return original_compile(self, *args, **kwargs)

    monkeypatch.setattr(DeterministicCompiler, "compile", counted_compile)

    report = asyncio.run(run_offline_replay(tmp_path / "evidence"))

    assert report["compile_count"] == 1
    assert compile_calls == 1
    assert report["artifact_hash"]
    assert [replay["profile"] for replay in report["replays"]] == ["A", "B"]
    assert all(replay["oracle"]["passed"] for replay in report["replays"])
    assert report["replays"][0]["run_id"] != report["replays"][1]["run_id"]
    assert report["replays"][0]["artifact_hash"] == report["artifact_hash"]
    assert report["replays"][1]["artifact_hash"] == report["artifact_hash"]
    assert report["replays"][1]["oracle"]["record_count"] == 1
    assert sum(round_["actual_actions"] for round_ in report["creation"]["browser_rounds"]) == sum(
        len(round_["candidate_ids"]) + len(round_.get("non_sop", ()))
        for round_ in report["creation"]["browser_rounds"]
    )
    assert "recording-sample-only" not in str(report)


def test_live_creation_builder_is_async_and_live_runner_uses_it() -> None:
    import live_first_skill_replay as live

    assert inspect.iscoroutinefunction(live._build_and_compile_live)
    source = inspect.getsource(live.run_live_replay)
    assert "_build_and_compile_live" in source
    assert "_build_and_compile(evidence_dir)" not in source
    assert '"adapter_rounds"' in source
    builder_source = inspect.getsource(live._build_and_compile_live)
    assert "execute_browser_use_instruction" in builder_source
    assert '"natural_language_agent_invoked": True' in builder_source
    assert '"agent_action_producer": "production-browser-use-executor"' in builder_source
    assert "BrowserUseRecordingAdapter(" not in builder_source
    assert "ActualToolAction(" not in builder_source
    assert "adapter.record_round" not in builder_source
    assert "index_ordinal" not in builder_source
    assert "business_type_recorded" not in builder_source
    assert '"action": "click_allowed_input"' in builder_source
    assert "invocation_count" in builder_source


def test_scripted_browser_use_model_selects_button_index_from_agent_messages() -> None:
    import live_first_skill_replay as live

    selector_map = "\n".join(
        (
            "[18]<li role=option>设备采购",
            "  [19]<button type=button>设备采购</button>",
            "PO-2026-05017",
            "  [42]<button type=button>发起验收</button>",
        )
    )
    assert live._ScriptedBrowserUseModel._selector_index(
        selector_map, "设备采购"
    ) == 19
    assert live._ScriptedBrowserUseModel._selector_index(
        selector_map, "<button", after="PO-2026-05017"
    ) == 42


def test_offline_profile_execution_failure_always_cleans_generated_modules(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import live_first_skill_replay as live

    loaded_packages: list[str] = []

    class BrokenSkill:
        async def execute_skill(self, _context) -> None:
            raise RuntimeError("injected profile failure")

    def load_broken_skill(_destination: Path, package_name: str) -> BrokenSkill:
        loaded_packages.append(package_name)
        for suffix in ("", ".skill", ".browser_segment"):
            sys.modules[package_name + suffix] = ModuleType(package_name + suffix)
        return BrokenSkill()

    monkeypatch.setattr(live, "_load_skill", load_broken_skill)

    with pytest.raises(RuntimeError, match="injected profile failure"):
        asyncio.run(live.run_offline_replay(tmp_path / "evidence"))

    assert loaded_packages == ["generated_first_skill_a"]
    assert not any(
        name in sys.modules
        for name in (
            "generated_first_skill_a",
            "generated_first_skill_a.skill",
            "generated_first_skill_a.browser_segment",
        )
    )


@pytest.mark.parametrize(
    "control_error",
    (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()),
)
def test_live_control_flow_errors_preserve_identity_cleanup_and_never_write_failure(
    control_error: BaseException,
) -> None:
    from live_first_skill_replay import (
        _cleanup_live_profile,
        _record_live_failure,
    )

    package_name = f"cancelled_package_{type(control_error).__name__.lower()}"
    for suffix in ("", ".skill", ".browser_segment"):
        sys.modules[package_name + suffix] = ModuleType(package_name + suffix)

    class Context:
        closed = False

        async def close(self) -> None:
            self.closed = True

    context = Context()
    replay: dict[str, object] = {}

    async def scenario() -> None:
        try:
            raise control_error
        except BaseException as exc:
            _record_live_failure(replay, exc, secrets=())
        finally:
            await _cleanup_live_profile(context, package_name)

    with pytest.raises(type(control_error)) as raised:
        asyncio.run(scenario())

    assert raised.value is control_error
    assert replay == {}
    assert context.closed
    assert not any(
        name in sys.modules
        for name in (package_name, f"{package_name}.skill", f"{package_name}.browser_segment")
    )


@pytest.mark.parametrize(
    "control_error",
    (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()),
)
@pytest.mark.parametrize(
    ("context_fails", "browser_fails"),
    ((True, False), (False, True), (True, True)),
)
def test_live_cleanup_failures_never_override_control_flow_primary(
    control_error: BaseException,
    context_fails: bool,
    browser_fails: bool,
) -> None:
    from live_first_skill_replay import _cleanup_live_browser, _cleanup_live_profile

    package_name = f"cleanup_priority_{type(control_error).__name__.lower()}"
    for suffix in ("", ".skill", ".browser_segment"):
        sys.modules[package_name + suffix] = ModuleType(package_name + suffix)

    class Resource:
        def __init__(self, fails: bool) -> None:
            self.fails = fails
            self.close_attempted = False

        async def close(self) -> None:
            self.close_attempted = True
            if self.fails:
                raise RuntimeError(
                    "cleanup-secret https://unsafe.invalid/?token=cleanup-token"
                )

    context = Resource(context_fails)
    browser = Resource(browser_fails)

    async def scenario() -> None:
        browser_primary: BaseException | None = None
        try:
            profile_primary: BaseException | None = None
            try:
                raise control_error
            except BaseException as exc:
                profile_primary = exc
                raise
            finally:
                await _cleanup_live_profile(
                    context,
                    package_name,
                    primary=profile_primary,
                )
        except BaseException as exc:
            browser_primary = exc
            raise
        finally:
            await _cleanup_live_browser(browser, primary=browser_primary)

    with pytest.raises(type(control_error)) as raised:
        asyncio.run(scenario())

    assert raised.value is control_error
    assert context.close_attempted
    assert browser.close_attempted
    assert getattr(control_error, "__notes__", []) == ["live_replay.cleanup_failed"]
    assert "cleanup-secret" not in str(getattr(control_error, "__notes__", []))
    assert "cleanup-token" not in str(getattr(control_error, "__notes__", []))
    assert "unsafe.invalid" not in str(getattr(control_error, "__notes__", []))
    assert not any(
        name in sys.modules
        for name in (package_name, f"{package_name}.skill", f"{package_name}.browser_segment")
    )


@pytest.mark.parametrize("resource_kind", ("context", "browser"))
def test_live_cleanup_failure_without_primary_is_safely_exposed(
    resource_kind: str,
) -> None:
    from live_first_skill_replay import _cleanup_live_browser, _cleanup_live_profile

    class Resource:
        async def close(self) -> None:
            raise RuntimeError("cleanup-secret https://unsafe.invalid/?token=cleanup-token")

    async def scenario() -> None:
        if resource_kind == "context":
            await _cleanup_live_profile(Resource(), "unused_cleanup_package")
        else:
            await _cleanup_live_browser(Resource())

    with pytest.raises(RuntimeError) as raised:
        asyncio.run(scenario())

    assert str(raised.value) == "live_replay.cleanup_failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    "control_type",
    (asyncio.CancelledError, KeyboardInterrupt, SystemExit),
)
@pytest.mark.parametrize(
    ("control_location", "later_browser_fails"),
    (("context", False), ("context", True), ("browser", False)),
)
def test_live_cleanup_control_flow_becomes_primary_after_successful_main_flow(
    control_type: type[BaseException],
    control_location: str,
    later_browser_fails: bool,
) -> None:
    from live_first_skill_replay import _cleanup_live_browser, _cleanup_live_profile

    control_error = control_type()
    package_name = f"cleanup_control_{control_location}_{control_type.__name__.lower()}"
    for suffix in ("", ".skill", ".browser_segment"):
        sys.modules[package_name + suffix] = ModuleType(package_name + suffix)

    class Resource:
        def __init__(self, error: BaseException | None = None) -> None:
            self.error = error
            self.close_attempted = False

        async def close(self) -> None:
            self.close_attempted = True
            if self.error is not None:
                raise self.error

    context = Resource(control_error if control_location == "context" else None)
    browser = Resource(
        control_error
        if control_location == "browser"
        else RuntimeError("unsafe browser cleanup token=secret")
        if later_browser_fails
        else None
    )

    async def scenario() -> None:
        browser_primary: BaseException | None = None
        try:
            await _cleanup_live_profile(context, package_name)
        except BaseException as exc:
            browser_primary = exc
            raise
        finally:
            await _cleanup_live_browser(browser, primary=browser_primary)

    with pytest.raises(control_type) as raised:
        asyncio.run(scenario())

    assert raised.value is control_error
    assert context.close_attempted
    assert browser.close_attempted
    expected_notes = ["live_replay.cleanup_failed"] if later_browser_fails else []
    assert getattr(control_error, "__notes__", []) == expected_notes
    assert "secret" not in str(getattr(control_error, "__notes__", []))
    assert not any(
        name in sys.modules
        for name in (package_name, f"{package_name}.skill", f"{package_name}.browser_segment")
    )


@pytest.mark.parametrize(
    "control_type",
    (asyncio.CancelledError, KeyboardInterrupt, SystemExit),
)
def test_existing_control_primary_wins_over_new_cleanup_control(
    control_type: type[BaseException],
) -> None:
    from live_first_skill_replay import _cleanup_live_browser

    primary = control_type()
    cleanup_control = control_type()

    class Browser:
        async def close(self) -> None:
            raise cleanup_control

    async def scenario() -> None:
        caught: BaseException | None = None
        try:
            raise primary
        except BaseException as exc:
            caught = exc
            raise
        finally:
            await _cleanup_live_browser(Browser(), primary=caught)

    with pytest.raises(control_type) as raised:
        asyncio.run(scenario())

    assert raised.value is primary
    assert getattr(primary, "__notes__", []) == ["live_replay.cleanup_failed"]


def test_load_skill_import_failure_cleans_partial_generated_package(tmp_path: Path) -> None:
    from live_first_skill_replay import _load_skill

    package_name = "partially_imported_generated_skill"
    (tmp_path / "browser_segment.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "skill.py").write_text(
        "raise RuntimeError('injected import failure')\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="injected import failure"):
        _load_skill(tmp_path, package_name)

    assert not any(
        name in sys.modules
        for name in (package_name, f"{package_name}.skill", f"{package_name}.browser_segment")
    )
