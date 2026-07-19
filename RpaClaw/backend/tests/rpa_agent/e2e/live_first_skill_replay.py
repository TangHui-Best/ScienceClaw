from __future__ import annotations

import asyncio
import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import re
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from rpa_agent.browser_use import ActualToolAction, BrowserUseRecordingAdapter, TargetResolution
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
from rpa_agent.runtime import RunContext
from rpa_agent.host import BrowserSession, PlaywrightBrowserSessionPort
from rpa_agent.api import AgentInstructionRequest
from rpa_agent.host.browser_use_agent import execute_browser_use_instruction
from rpa_agent.host.manual_input import ManualInputCommand


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)
FRAME_PATH = ({"name": "Acceptance form", "locators": [{"strategy": "title", "value": "验收登记表单", "exact": True}]},)
RECORDING = {
    "business_type": "设备采购",
    "date_from": "2026-05-01",
    "date_to": "2026-05-31",
    "supplier_name": "华东精密设备有限公司",
    "order_no": "PO-2026-05017",
}
TARGET_LOCATORS = {
    "business-type": {"strategy": "role", "role": "combobox", "name": "业务类型", "exact": True},
    "query-date_from": {"strategy": "label", "value": "订单日期（起）", "exact": True},
    "query-date_to": {"strategy": "label", "value": "订单日期（止）", "exact": True},
    "query-supplier_name": {"strategy": "label", "value": "供应商名称", "exact": True},
    "query-order_no": {"strategy": "label", "value": "订单编号", "exact": True},
    "query-submit": {"strategy": "role", "role": "button", "name": "查询", "exact": True},
    "start-acceptance": {"strategy": "role", "role": "button"},
    "order-no": {"strategy": "label", "value": "来源订单号", "exact": True},
    "supplier-name": {"strategy": "label", "value": "供应商", "exact": True},
    "contract-no": {"strategy": "label", "value": "合同号", "exact": True},
    "amount": {"strategy": "label", "value": "验收金额", "exact": True},
    "currency": {"strategy": "role", "role": "combobox", "name": "币种", "exact": True},
    "order-date": {"strategy": "label", "value": "订单日期", "exact": True},
    "description": {"strategy": "label", "value": "验收说明", "exact": True},
    "confirmed": {"strategy": "label", "value": "已核对以上信息并确认无误", "exact": True},
    "save-acceptance": {"strategy": "role", "role": "button", "name": "保存", "exact": True},
    "confirm-acceptance": {"strategy": "role", "role": "button", "name": "确认提交", "exact": True},
    "acceptance-result": {"strategy": "css", "value": "[role='status'].success"},
}
PROFILES = {
    "A": {
        "inputs": dict(RECORDING),
        "order": {"order_no": "PO-2026-05017", "supplier_name": "华东精密设备有限公司", "contract_no": "CT-2026-0088", "amount": "128600.50", "currency": "CNY", "order_date": "2026-05-16"},
        "target_position": 0,
    },
    "B": {
        "inputs": {**RECORDING, "business_type": "服务采购", "date_from": "2026-06-01", "date_to": "2026-06-30", "supplier_name": "北辰数字技术有限公司", "order_no": "PO-2026-06042"},
        "order": {"order_no": "PO-2026-06042", "supplier_name": "北辰数字技术有限公司", "contract_no": "CT-2026-0116", "amount": "10150.75", "currency": "USD", "order_date": "2026-06-08"},
        "target_position": 2,
    },
}


def _target(test_id: str, name: str | None = None) -> dict[str, object]:
    return {"name": name or test_id, "locators": [dict(TARGET_LOCATORS[test_id])]}


def _variable(name: str, ref: str, *, direction: str = "input") -> dict[str, object]:
    return {"name": name, "direction": direction, "kind_hint": "variable", "ref_hint": ref, "sensitive": False}


def _skill_input(name: str, ref: str) -> dict[str, object]:
    return {"name": name, "direction": "input", "kind_hint": "skill_input", "ref_hint": ref, "sensitive": False}


def _manual_fill(session: SkillCreationSession, candidate_id: str, test_id: str, value: str, at: datetime) -> None:
    reservation = session.reserve_manual(candidate_id=candidate_id, page_runtime_ref="runtime_main", frame_runtime_ref="main_frame")
    common = dict(page_runtime_ref="runtime_main", frame_runtime_ref="main_frame", target_key=test_id, target_name=test_id, target_locators=(_target(test_id)["locators"][0],), interaction_kind=InteractionKind.FILL)
    session.ingest_manual(reservation, ManualEvent(kind=ManualEventKind.BEFORE_INPUT, observed_at=at, **common))
    session.ingest_manual(reservation, ManualEvent(kind=ManualEventKind.INPUT, observed_at=at + timedelta(milliseconds=1), value=value, **common))
    emitted = session.ingest_manual(reservation, ManualEvent(kind=ManualEventKind.BLUR, observed_at=at + timedelta(milliseconds=2), **common))
    assert len(emitted) == 1
    session.finish_manual_candidate(reservation, at=at + timedelta(milliseconds=3))


def _manual_click(
    session: SkillCreationSession,
    candidate_id: str,
    test_id: str,
    at: datetime,
    *,
    path: tuple[dict[str, object], ...] = (),
    bindings: tuple[dict[str, object], ...] = (),
    popup: bool = False,
    locator: dict[str, object] | None = None,
) -> None:
    reservation = session.reserve_manual(candidate_id=candidate_id, page_runtime_ref="runtime_main", frame_runtime_ref="main_frame")
    trigger = session.observer.start_new_page("runtime_main", "main_frame") if popup else None
    emitted = session.ingest_manual(
        reservation,
        ManualEvent(
            kind=ManualEventKind.CLICK,
            page_runtime_ref="runtime_main",
            frame_runtime_ref="main_frame",
            target_key=test_id,
            target_name=test_id,
            target_locators=(locator or _target(test_id)["locators"][0],),
            target_path=path,
            binding_hints=bindings,
            interaction_kind=InteractionKind.CLICK,
            observed_at=at,
        ),
    )
    assert len(emitted) == 1
    if trigger is not None:
        fact = session.observer.complete_new_page(
            trigger,
            observed_at=at + timedelta(milliseconds=1),
            new_page_runtime_ref="runtime_popup",
            initial_url="https://eval.invalid/system-b/acceptance/random-token",
        )
        assert session.pages.apply(fact) == "page_001"
    session.finish_manual_candidate(reservation, at=at + timedelta(milliseconds=2))


async def _record_agent_round(session: SkillCreationSession, actions: list[ActualToolAction], now: datetime):
    async def execute(_action: ActualToolAction) -> dict[str, object]:
        return {"success": True, "is_done": _action.action_name == "done"}

    async def evidence(action: ActualToolAction, _result: object) -> dict[str, object]:
        if action.action_name == "input":
            return {"dom_value": action.params["text"]}
        if action.action_name == "select_dropdown":
            return {"selected": action.params["option"]}
        if action.action_name == "click":
            return {"dispatched": True}
        if action.action_name == "evaluate":
            return {"completed": True, "variables": {"purchase_order": PROFILES["A"]["order"]}}
        if action.action_name == "extract":
            return {"variables": {"acceptance_result": "accepted"}}
        return {}

    async def resolve(action: ActualToolAction) -> TargetResolution:
        return TargetResolution(target_hint=action.target_hint, match_count=1 if action.target_hint else 0)

    return await BrowserUseRecordingAdapter(
        session=session,
        executor=execute,
        evidence_provider=evidence,
        target_resolver=resolve,
        version_provider=lambda: "0.13.2",
        clock=lambda: now,
    ).record_round(actions, completed_at=now)


def _action(
    action_name: str,
    candidate_id: str,
    *,
    page_ref: str,
    runtime_page_ref: str,
    frame_path: tuple[dict[str, object], ...] = (),
    target: dict[str, object] | None = None,
    params: dict[str, object] | None = None,
    bindings: tuple[dict[str, object], ...] = (),
    intent: str | None = None,
) -> ActualToolAction:
    return ActualToolAction(
        action_name=action_name,
        candidate_id=candidate_id,
        params=params or {},
        business_intent=intent or candidate_id,
        runtime_page_ref=runtime_page_ref,
        runtime_frame_ref="acceptance_frame" if frame_path else "main_frame",
        page_ref=page_ref,
        frame_path=frame_path,
        target_hint=target,
        binding_hints=bindings,
    )


async def _build_and_compile(evidence_dir: Path):
    session = SkillCreationSession(session_id="first_vertical_e2e", main_runtime_ref="runtime_main", fact_buffer_capacity=64, fact_ttl=timedelta(minutes=2))
    _manual_click(session, "manual_business_type_open", "business-type", NOW)
    _manual_click(
        session,
        "manual_business_type_option",
        "business-type-option",
        NOW + timedelta(seconds=1),
        path=({"name": "Matching business type option", "locators": [{"strategy": "role", "role": "option"}], "filter_binding": "option"},),
        bindings=({"name": "option", "direction": "input", "kind_hint": "skill_input", "ref_hint": "business_type", "sensitive": False},),
        locator={"strategy": "role", "role": "button"},
    )
    manual_fields = [(name, value) for name, value in RECORDING.items() if name != "business_type"]
    for index, (name, value) in enumerate(manual_fields, start=2):
        _manual_fill(session, f"manual_query_{name}", f"query-{name}", value, NOW + timedelta(seconds=index))
    _manual_click(session, "manual_query_submit", "query-submit", NOW + timedelta(seconds=7))

    session.switch_control(ControlMode.AGENT, at=NOW + timedelta(seconds=8))
    extract_report = await _record_agent_round(
        session,
        [_action("evaluate", "agent_extract_purchase_order", page_ref="main", runtime_page_ref="runtime_main", bindings=(_skill_input("order_no", "order_no"), _variable("purchase_order", "purchase_order", direction="output")), intent="Extract the matching purchase order business fields")],
        NOW + timedelta(seconds=9),
    )
    session.switch_control(ControlMode.HUMAN, at=NOW + timedelta(seconds=10))
    _manual_click(
        session,
        "manual_open_acceptance",
        "start-acceptance",
        NOW + timedelta(seconds=11),
        path=({"name": "Matching order row", "locators": [{"strategy": "role", "role": "row"}], "filter_binding": "row_key"},),
        bindings=({"name": "row_key", "direction": "input", "kind_hint": "skill_input", "ref_hint": "order_no", "sensitive": False},),
        popup=True,
    )
    session.switch_control(ControlMode.AGENT, at=NOW + timedelta(seconds=12))

    field_specs = (
        ("order_no", "order-no", "purchase_order.order_no"),
        ("supplier_name", "supplier-name", "purchase_order.supplier_name"),
        ("contract_no", "contract-no", "purchase_order.contract_no"),
        ("amount", "amount", "purchase_order.amount"),
        ("order_date", "order-date", "purchase_order.order_date"),
    )
    actions = [
        _action("input", f"agent_fill_{name}", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target=_target(test_id), params={"text": f"recorded-{name}"}, bindings=(_variable("value", ref),))
        for name, test_id, ref in field_specs
    ]
    actions.extend(
        [
            _action("click", "agent_supplier_option", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target={"name": "Matching supplier option", "path": [{"name": "Supplier option", "locators": [{"strategy": "role", "role": "option"}], "filter_binding": "option"}], "locators": [{"strategy": "role", "role": "button"}]}, bindings=(_variable("option", "purchase_order.supplier_name"),)),
            _action("click", "agent_currency_open", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target=_target("currency")),
            _action("click", "agent_currency_option", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target={"name": "Matching currency option", "path": [{"name": "Currency option", "locators": [{"strategy": "role", "role": "option"}], "filter_binding": "option"}], "locators": [{"strategy": "role", "role": "button"}]}, bindings=(_variable("option", "purchase_order.currency"),)),
            _action("input", "agent_fill_description", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target=_target("description"), params={"text": "自动创建"}),
            _action("click", "agent_confirm_checkbox", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target=_target("confirmed")),
            _action("click", "agent_save_acceptance", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target=_target("save-acceptance")),
            _action("click", "agent_confirm_acceptance", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target=_target("confirm-acceptance")),
            _action("extract", "agent_extract_result", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, target=_target("acceptance-result"), params={"mode": "text"}, bindings=(_variable("result", "acceptance_result", direction="output"),)),
            _action("done", "agent_done", page_ref="page_001", runtime_page_ref="runtime_popup", frame_path=FRAME_PATH, intent="Finish this Browser-use round"),
        ]
    )
    form_report = await _record_agent_round(session, actions, NOW + timedelta(seconds=13))

    for candidate_id, candidate in session.candidates.items():
        scope = BrowserScope(page_ref="page_001", frame_path=list(FRAME_PATH)) if candidate_id.startswith("agent_") and candidate_id != "agent_extract_purchase_order" else BrowserScope(page_ref="main", frame_path=[])
        if candidate_id == "manual_open_acceptance":
            scope = BrowserScope(page_ref="main", frame_path=[])
        outcome = session.settle_candidate(candidate_id, scope=scope)
        assert outcome.status == "accepted", (candidate_id, outcome)
    readiness = session.build_readiness()
    assert readiness.ready and not readiness.issues, readiness.issues

    promotions = []
    for name in RECORDING:
        if name == "business_type":
            continue
        trace_id = session.accepted_traces[f"manual_query_{name}"].trace_id
        promotions.append({"trace_id": trace_id, "binding_name": "value", "to_kind": "skill_input", "ref": name})
    configured = transform_configuration(
        readiness,
        SkillConfigurationDraft.model_validate(
            {
                "schema_version": "skill-configuration-draft/v0.1",
                "skill": {"name": "Purchase order acceptance", "description": "Recorded query, extraction, row selection and iframe acceptance."},
                "inputs": [{"ref": name, "title": name, "value_type": "string", "required": True} for name in RECORDING],
                "secrets": [], "asset_inputs": [],
                "outputs": [{"name": "acceptance_result", "title": "Acceptance result", "variable_ref": "acceptance_result", "value_type": "string"}],
                "asset_outputs": [], "binding_promotions": promotions, "stage_2_rules": None,
            }
        ),
        skill_id="first-purchase-order-acceptance",
    )
    destination = evidence_dir / "compiled_skill"
    class CountingCompiler:
        def __init__(self) -> None:
            self.count = 0
            self.delegate = DeterministicCompiler()

        def compile(self, *args, **kwargs):
            self.count += 1
            return self.delegate.compile(*args, **kwargs)

    compiler = CountingCompiler()
    compiled = compiler.compile(configured.timeline, configured.skill_definition, destination)
    assert compiled.status == "published", compiled.issues
    assert compiled.artifacts is not None
    corpus = "\n".join(compiled.artifacts.files.values())
    forbidden_business_values = {
        str(value)
        for profile in PROFILES.values()
        for source in (profile["inputs"], profile["order"])
        for value in source.values()
    }
    assert not sorted(value for value in forbidden_business_values if value in corpus)
    forbidden_fragments = (
        ".first(",
        ".nth(",
        "backend.rpa",
        "browser-use history",
        "task-",
        "token=",
        "about:blank",
        "https://eval.invalid/system-b/acceptance/random-token",
    )
    assert not [fragment for fragment in forbidden_fragments if fragment in corpus.lower()]
    artifact_hash = hashlib.sha256("".join(f"{name}\0{compiled.artifacts.files[name]}" for name in sorted(compiled.artifacts.files)).encode()).hexdigest()
    return session, configured, destination, artifact_hash, extract_report, form_report, compiler.count


@dataclass(frozen=True, slots=True)
class _LiveCreationBuild:
    session: SkillCreationSession
    configured: object
    destination: Path
    artifact_hash: str
    adapter_rounds: tuple[object, ...]
    compile_count: int
    evidence: dict[str, object]


class _ScriptedBrowserUseModel:
    """Deterministic LLM boundary: decides Tools actions from Agent messages only."""

    model = "scripted-browser-use-e2e"
    model_name = model
    provider = "scripted"
    name = model

    def __init__(self, steps: list[dict[str, object]]) -> None:
        self._steps = list(steps)
        self.invocation_count = 0

    @staticmethod
    def _messages_text(messages: list[object]) -> str:
        for message in reversed(messages):
            text = getattr(message, "text", None)
            if isinstance(text, str):
                return text
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content
        return ""

    @staticmethod
    def _selector_index(text: str, marker: str, *, after: str | None = None) -> int:
        lines = text.splitlines()
        start = 0
        if after is not None:
            matching_starts = [index for index, line in enumerate(lines) if after in line]
            scoped_matches: list[tuple[int, str]] = []
            for matching_start in matching_starts:
                for line in lines[matching_start : matching_start + 16]:
                    if marker not in line:
                        continue
                    match = re.search(r"\[(\d+)\]", line)
                    if match is not None:
                        scoped_matches.append((int(match.group(1)), line))
                        break
            scoped_unique = tuple(
                dict.fromkeys(index for index, _line in scoped_matches)
            )
            if len(scoped_unique) == 1:
                return scoped_unique[0]
            raise RuntimeError(f"live_creation.agent_marker_not_unique:{after}")
        matches: list[tuple[int, str]] = []
        for line in lines[start:]:
            if marker not in line:
                continue
            match = re.search(r"\[(\d+)\]", line)
            if match is not None:
                matches.append((int(match.group(1)), line))
            if after is not None and matches:
                break
        unique = tuple(dict.fromkeys(index for index, _line in matches))
        if len(unique) > 1:
            buttons = tuple(
                dict.fromkeys(index for index, line in matches if "<button" in line)
            )
            if len(buttons) == 1:
                return buttons[0]
        if len(unique) != 1:
            sample = " || ".join(line.strip()[:120] for _index, line in matches[:4])
            if not sample:
                diagnostic_lines = [
                    line.strip()[:160]
                    for line in lines
                    if "business-type" in line
                    or "option" in line.lower()
                    or "dialog" in line.lower()
                    or "<button" in line.lower()
                    or "涓氬姟绫诲瀷" in line
                ]
                sample = " || ".join(diagnostic_lines[:6])
            raise RuntimeError(
                f"live_creation.agent_selector_not_unique:{marker}:{sample}"
            )
        return unique[0]

    async def ainvoke(self, messages: list[object], output_format=None, **_kwargs):
        from browser_use.llm.views import ChatInvokeCompletion

        if output_format is None or not self._steps:
            raise RuntimeError("live_creation.scripted_model_plan_exhausted")
        text = self._messages_text(messages)
        step = self._steps[0]
        observe = step.get("observe")
        if isinstance(observe, str) and observe not in text:
            raise RuntimeError(f"live_creation.agent_observation_missing:{observe}")
        observe_all = step.get("observe_all")
        if isinstance(observe_all, (list, tuple)):
            missing = [str(item) for item in observe_all if str(item) not in text]
            if missing:
                raise RuntimeError(
                    "live_creation.agent_observations_missing:" + ",".join(missing)
                )
        params = dict(step.get("params", {}))
        value_from_observation = step.get("value_from_observation")
        if isinstance(value_from_observation, str):
            if value_from_observation not in text:
                raise RuntimeError(
                    "live_creation.agent_observation_missing:"
                    + value_from_observation
                )
            params["value"] = value_from_observation
        marker = step.get("index_marker")
        if isinstance(marker, str):
            params["index"] = self._selector_index(
                text,
                marker,
                after=(
                    step.get("after")
                    if isinstance(step.get("after"), str)
                    else None
                ),
            )
        payload = {
            "thinking": "Follow the deterministic E2E instruction plan.",
            "evaluation_previous_goal": "The previous tool result was checked by the Agent loop.",
            "memory": f"scripted-step-{self.invocation_count}",
            "next_goal": str(step["action"]),
            "action": [{str(step["action"]): params}],
        }
        self._steps.pop(0)
        self.invocation_count += 1
        return ChatInvokeCompletion(
            completion=output_format.model_validate(payload),
            usage=None,
        )

    @property
    def complete(self) -> bool:
        return not self._steps


def _live_agent_factory(**kwargs: object):
    from browser_use import Agent

    kwargs.update(
        {
            "enable_planning": False,
            "use_judge": False,
            "message_compaction": False,
            "final_response_after_failure": False,
            "max_history_items": 6,
            "directly_open_url": False,
        }
    )
    return Agent(**kwargs)


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _playwright_locator(scope: object, spec: dict[str, object]):
    strategy = spec["strategy"]
    exact = bool(spec.get("exact", True))
    if strategy == "role":
        return scope.get_by_role(
            spec["role"],
            name=spec.get("name"),
            exact=exact,
        )
    if strategy == "test_id":
        return scope.get_by_test_id(spec["value"])
    if strategy == "label":
        return scope.get_by_label(spec["value"], exact=exact)
    if strategy == "placeholder":
        return scope.get_by_placeholder(spec["value"], exact=exact)
    if strategy == "text":
        return scope.get_by_text(spec["value"], exact=exact)
    if strategy == "title":
        return scope.get_by_title(spec["value"], exact=exact)
    if strategy == "alt_text":
        return scope.get_by_alt_text(spec["value"], exact=exact)
    if strategy in {"css", "xpath"}:
        return scope.locator(spec["value"])
    raise ValueError("live_creation.locator_strategy_unknown")


async def _manual_locator_point(locator: object) -> tuple[float, float]:
    if await locator.count() != 1:
        raise RuntimeError("live_creation.manual_target_not_unique")
    box = await locator.bounding_box()
    if not box:
        raise RuntimeError("live_creation.manual_target_not_visible")
    return (
        float(box["x"]) + min(4.0, float(box["width"]) / 2),
        float(box["y"]) + min(4.0, float(box["height"]) / 2),
    )


async def _build_and_compile_live_direct_fixture(
    evidence_dir: Path,
    *,
    page: object,
    context: object,
) -> _LiveCreationBuild:
    """Create the artifact from real Playwright DOM actions in one session."""

    session = SkillCreationSession(
        session_id="first_vertical_live_creation",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=128,
        fact_ttl=timedelta(minutes=2),
    )
    page_refs: dict[int, str] = {id(page): "runtime_main"}
    frame_refs: dict[int, str] = {id(page.main_frame): "main_frame"}
    pages_by_ref: dict[str, object] = {"runtime_main": page}
    frames_by_ref: dict[str, object] = {"main_frame": page.main_frame}

    def page_runtime_ref(target: object) -> str:
        key = id(target)
        if key not in page_refs:
            page_refs[key] = (
                "runtime_popup"
                if "runtime_popup" not in pages_by_ref
                else f"runtime_page_{len(page_refs) + 1}"
            )
        runtime_ref = page_refs[key]
        pages_by_ref[runtime_ref] = target
        return runtime_ref

    def frame_runtime_ref(target: object) -> str:
        key = id(target)
        if key not in frame_refs:
            name = str(getattr(target, "name", ""))
            if name == "acceptance-form" and "acceptance_frame" not in frames_by_ref:
                frame_refs[key] = "acceptance_frame"
            else:
                frame_refs[key] = f"runtime_frame_{len(frame_refs) + 1}"
        runtime_ref = frame_refs[key]
        frames_by_ref[runtime_ref] = target
        return runtime_ref

    def frame_path(_page_ref: str, frame_ref: str):
        return FRAME_PATH if frame_ref == "acceptance_frame" else ()

    port = PlaywrightBrowserSessionPort(
        context=context,
        main_page=page,
        main_page_runtime_ref="runtime_main",
        main_frame_runtime_ref="main_frame",
        page_runtime_ref=page_runtime_ref,
        frame_runtime_ref=frame_runtime_ref,
        frame_path=frame_path,
        page_main_frame_runtime_ref=lambda target: frame_runtime_ref(target.main_frame),
        active_page=lambda: page,
    )
    browser_session = BrowserSession(port=port, creation=session)
    browser_session.attach()
    manual_candidates: dict[str, str] = {}
    state: dict[str, object] = {"popup": None, "frame": None}

    async def manual_click(input_id: str, locator: object) -> str:
        x, y = await _manual_locator_point(locator)
        result = await browser_session.dispatch_manual_input(
            ManualInputCommand(input_id=input_id, kind="click", x=x, y=y)
        )
        if not result.candidate_id:
            raise RuntimeError("live_creation.manual_candidate_missing")
        return result.candidate_id

    async def manual_fill(name: str, value: str) -> str:
        locator = _playwright_locator(page, TARGET_LOCATORS[f"query-{name}"])
        candidate_id = await manual_click(f"live_focus_{name}", locator)
        result = await browser_session.dispatch_manual_input(
            ManualInputCommand(
                input_id=f"live_text_{name}",
                kind="text",
                text=value,
            )
        )
        if result.candidate_id != candidate_id:
            raise RuntimeError("live_creation.manual_fill_candidate_changed")
        manual_candidates[name] = candidate_id
        return candidate_id

    def binding_value(action: ActualToolAction, name: str) -> object:
        matches = [
            item
            for item in action.binding_hints
            if item.get("name") == name and item.get("direction") == "input"
        ]
        if len(matches) != 1:
            raise RuntimeError("live_creation.binding_not_unique")
        binding = matches[0]
        kind = binding.get("kind_hint")
        if kind == "skill_input":
            return RECORDING[str(binding["ref_hint"])]
        if kind == "variable":
            return session.variables.read(str(binding["ref_hint"]))
        if kind == "literal":
            return binding.get("value")
        raise RuntimeError("live_creation.binding_kind_unknown")

    def input_value(action: ActualToolAction) -> object:
        matching_bindings = [
            item
            for item in action.binding_hints
            if item.get("name") == "value" and item.get("direction") == "input"
        ]
        if matching_bindings:
            return binding_value(action, "value")
        if "text" in action.params:
            return action.params["text"]
        raise RuntimeError("live_creation.input_value_missing")

    async def action_locator(action: ActualToolAction):
        candidate_id = action.candidate_id
        if candidate_id == "agent_business_type_option":
            option = str(binding_value(action, "option"))
            return page.get_by_role("option").filter(has_text=option).get_by_role("button")
        if candidate_id == "agent_date_from":
            return _playwright_locator(page, TARGET_LOCATORS["query-date_from"])
        if candidate_id == "agent_date_to":
            return _playwright_locator(page, TARGET_LOCATORS["query-date_to"])
        if candidate_id == "agent_extract_purchase_order":
            order_no = RECORDING["order_no"]
            return page.get_by_role("row").filter(has_text=order_no)
        if candidate_id == "agent_open_acceptance":
            order = session.variables.read("purchase_order")
            return (
                page.get_by_role("row")
                .filter(has_text=str(order["order_no"]))
                .get_by_role("button")
            )
        frame = state.get("frame")
        if frame is None:
            return None
        target_by_candidate = {
            "agent_fill_order_no": "order-no",
            "agent_fill_supplier_name": "supplier-name",
            "agent_fill_contract_no": "contract-no",
            "agent_fill_amount": "amount",
            "agent_fill_order_date": "order-date",
            "agent_currency_open": "currency",
            "agent_fill_description": "description",
            "agent_confirm_checkbox": "confirmed",
            "agent_save_acceptance": "save-acceptance",
            "agent_confirm_acceptance": "confirm-acceptance",
            "agent_extract_result": "acceptance-result",
        }
        if candidate_id in target_by_candidate:
            return _playwright_locator(
                frame,
                TARGET_LOCATORS[target_by_candidate[candidate_id]],
            )
        if candidate_id == "agent_supplier_option":
            option = str(binding_value(action, "option"))
            return frame.get_by_role("option").filter(has_text=option).get_by_role("button")
        if candidate_id == "agent_currency_option":
            option = str(binding_value(action, "option"))
            return frame.get_by_role("option").filter(has_text=option).get_by_role("button")
        return None

    async def resolve(action: ActualToolAction) -> TargetResolution:
        locator = await action_locator(action)
        match_count = await locator.count() if locator is not None else 0
        return TargetResolution(
            target_hint=action.target_hint,
            match_count=match_count,
        )

    async def execute(action: ActualToolAction) -> dict[str, object]:
        if action.action_name == "done":
            return {"success": True, "is_done": True}
        locator = await action_locator(action)
        if locator is None or await locator.count() != 1:
            raise RuntimeError(
                f"live_creation.agent_target_not_unique:{action.candidate_id}"
            )
        if action.action_name == "evaluate":
            cells = await locator.locator("td").all_inner_texts()
            if len(cells) < 6:
                raise RuntimeError("live_creation.order_row_shape_invalid")
            purchase_order = {
                "order_no": cells[0].strip(),
                "supplier_name": cells[1].strip(),
                "contract_no": cells[2].strip(),
                "amount": cells[3].strip(),
                "currency": cells[4].strip(),
                "order_date": cells[5].strip(),
            }
            return {"success": True, "variables": {"purchase_order": purchase_order}}
        if action.action_name == "extract":
            text = (await locator.inner_text()).strip()
            if not text:
                raise RuntimeError("live_creation.result_empty")
            return {"success": True, "variables": {"acceptance_result": text}}

        target_page = page if action.runtime_page_ref == "runtime_main" else state["popup"]
        if target_page is None:
            raise RuntimeError("live_creation.action_page_missing")
        scope = SimpleNamespace(
            page=target_page,
            page_runtime_ref=action.runtime_page_ref,
            frame_runtime_ref=action.runtime_frame_ref,
        )
        async with port.action_dispatch_scope(scope):
            if action.action_name == "input":
                value = str(input_value(action))
                await locator.fill(value)
                return {"success": True, "dom_value": await locator.input_value()}
            if action.action_name != "click":
                raise RuntimeError("live_creation.agent_action_unknown")
            if action.candidate_id == "agent_open_acceptance":
                async with context.expect_page() as popup_info:
                    await locator.click()
                popup = await popup_info.value
                state["popup"] = popup
                popup_ref = page_runtime_ref(popup)
                if popup_ref != "runtime_popup":
                    raise RuntimeError("live_creation.popup_runtime_ref_invalid")
                frame_title = str(FRAME_PATH[0]["locators"][0]["value"])
                await popup.get_by_title(frame_title, exact=True).wait_for(state="visible")
                acceptance_frame = popup.frame(name="acceptance-form")
                if acceptance_frame is None:
                    raise RuntimeError("live_creation.acceptance_frame_missing")
                frame_runtime_ref(acceptance_frame)
                state["frame"] = acceptance_frame
            else:
                await locator.click()
                if action.candidate_id == "agent_confirm_acceptance":
                    frame = state["frame"]
                    await frame.get_by_role("status").wait_for(state="visible")
            return {"success": True, "dispatched": True}

    async def evidence(
        action: ActualToolAction,
        result: dict[str, object],
    ) -> dict[str, object]:
        if action.action_name == "input":
            return {"dom_value": result.get("dom_value")}
        if action.action_name == "click":
            return {"dispatched": result.get("dispatched", True)}
        if action.action_name == "evaluate":
            return {"completed": True, "variables": result["variables"]}
        if action.action_name == "extract":
            return {"variables": result["variables"]}
        return {}

    async def record_round(actions: list[ActualToolAction]):
        now = datetime.now(timezone.utc)
        return await BrowserUseRecordingAdapter(
            session=session,
            executor=execute,
            evidence_provider=evidence,
            target_resolver=resolve,
            version_provider=lambda: "0.13.2",
            clock=lambda: now,
        ).record_round(actions, completed_at=now)

    try:
        await manual_fill("supplier_name", RECORDING["supplier_name"])
        await manual_fill("order_no", RECORDING["order_no"])
        business_open_id = await manual_click(
            "live_business_type_open",
            _playwright_locator(page, TARGET_LOCATORS["business-type"]),
        )
        manual_candidates["business_type_open"] = business_open_id
        browser_session.enter_agent_control(at=datetime.now(timezone.utc))

        business_option_target = {
            "name": "Matching business type option",
            "path": [
                {
                    "name": "Business type option",
                    "locators": [{"strategy": "role", "role": "option"}],
                    "filter_binding": "option",
                }
            ],
            "locators": [{"strategy": "role", "role": "button"}],
        }
        setup_report = await record_round(
            [
                _action(
                    "click",
                    "agent_business_type_option",
                    page_ref="main",
                    runtime_page_ref="runtime_main",
                    target=business_option_target,
                    bindings=(_skill_input("option", "business_type"),),
                ),
                _action(
                    "input",
                    "agent_date_from",
                    page_ref="main",
                    runtime_page_ref="runtime_main",
                    target=_target("query-date_from"),
                    params={"text": RECORDING["date_from"]},
                    bindings=(_skill_input("value", "date_from"),),
                ),
                _action(
                    "input",
                    "agent_date_to",
                    page_ref="main",
                    runtime_page_ref="runtime_main",
                    target=_target("query-date_to"),
                    params={"text": RECORDING["date_to"]},
                    bindings=(_skill_input("value", "date_to"),),
                ),
            ]
        )

        session.switch_control(ControlMode.HUMAN, at=datetime.now(timezone.utc))
        manual_candidates["query_submit"] = await manual_click(
            "live_query_submit",
            _playwright_locator(page, TARGET_LOCATORS["query-submit"]),
        )
        target_row = page.get_by_role("row").filter(has_text=RECORDING["order_no"])
        await target_row.wait_for(state="visible")
        browser_session.enter_agent_control(at=datetime.now(timezone.utc))

        row_target = {
            "name": "Matching order acceptance button",
            "path": [
                {
                    "name": "Matching order row",
                    "locators": [{"strategy": "role", "role": "row"}],
                    "filter_binding": "row_key",
                }
            ],
            "locators": [{"strategy": "role", "role": "button"}],
        }
        extraction_report = await record_round(
            [
                _action(
                    "evaluate",
                    "agent_extract_purchase_order",
                    page_ref="main",
                    runtime_page_ref="runtime_main",
                    bindings=(
                        _skill_input("order_no", "order_no"),
                        _variable("purchase_order", "purchase_order", direction="output"),
                    ),
                    intent="Extract the matching purchase order business fields",
                ),
                _action(
                    "click",
                    "agent_open_acceptance",
                    page_ref="main",
                    runtime_page_ref="runtime_main",
                    target=row_target,
                    bindings=(_variable("row_key", "purchase_order.order_no"),),
                    intent="Open acceptance for the extracted purchase order",
                ),
            ]
        )

        if session.pages.resolve("runtime_popup") != "page_001":
            raise RuntimeError("live_creation.popup_page_not_registered")
        field_specs = (
            ("order_no", "order-no", "purchase_order.order_no"),
            ("supplier_name", "supplier-name", "purchase_order.supplier_name"),
            ("contract_no", "contract-no", "purchase_order.contract_no"),
            ("amount", "amount", "purchase_order.amount"),
            ("order_date", "order-date", "purchase_order.order_date"),
        )
        form_actions = [
            _action(
                "input",
                f"agent_fill_{name}",
                page_ref="page_001",
                runtime_page_ref="runtime_popup",
                frame_path=FRAME_PATH,
                target=_target(test_id),
                params={"text": str(PROFILES["A"]["order"][name])},
                bindings=(_variable("value", ref),),
            )
            for name, test_id, ref in field_specs
        ]
        form_actions.extend(
            [
                _action(
                    "click",
                    "agent_supplier_option",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    target={
                        "name": "Matching supplier option",
                        "path": [
                            {
                                "name": "Supplier option",
                                "locators": [{"strategy": "role", "role": "option"}],
                                "filter_binding": "option",
                            }
                        ],
                        "locators": [{"strategy": "role", "role": "button"}],
                    },
                    bindings=(_variable("option", "purchase_order.supplier_name"),),
                ),
                _action(
                    "click",
                    "agent_currency_open",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    target=_target("currency"),
                ),
                _action(
                    "click",
                    "agent_currency_option",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    target={
                        "name": "Matching currency option",
                        "path": [
                            {
                                "name": "Currency option",
                                "locators": [{"strategy": "role", "role": "option"}],
                                "filter_binding": "option",
                            }
                        ],
                        "locators": [{"strategy": "role", "role": "button"}],
                    },
                    bindings=(_variable("option", "purchase_order.currency"),),
                ),
                _action(
                    "input",
                    "agent_fill_description",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    target=_target("description"),
                    params={"text": "自动创建"},
                ),
                _action(
                    "click",
                    "agent_confirm_checkbox",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    target=_target("confirmed"),
                ),
                _action(
                    "click",
                    "agent_save_acceptance",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    target=_target("save-acceptance"),
                ),
                _action(
                    "click",
                    "agent_confirm_acceptance",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    target=_target("confirm-acceptance"),
                ),
                _action(
                    "extract",
                    "agent_extract_result",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    target=_target("acceptance-result"),
                    params={"mode": "text"},
                    bindings=(
                        _variable("result", "acceptance_result", direction="output"),
                    ),
                ),
                _action(
                    "done",
                    "agent_done",
                    page_ref="page_001",
                    runtime_page_ref="runtime_popup",
                    frame_path=FRAME_PATH,
                    intent="Finish this Browser-use round",
                ),
            ]
        )
        form_report = await record_round(form_actions)
        await browser_session.drain_pending_facts(timeout=5)

        for candidate_id, candidate in session.candidates.items():
            if candidate_id in session.accepted_traces or candidate_id in session.diagnostics:
                continue
            scope_hint = candidate.scope_hint.model_dump(exclude_none=True)
            outcome = session.settle_candidate(
                candidate_id,
                scope=BrowserScope.model_validate(scope_hint),
            )
            if getattr(outcome, "status", None) != "accepted":
                raise RuntimeError(f"live_creation.settlement_failed:{candidate_id}")
        readiness = session.build_readiness()
        if not readiness.ready or readiness.issues:
            raise RuntimeError("live_creation.build_not_ready")

        promotions = [
            {
                "trace_id": session.accepted_traces[manual_candidates[name]].trace_id,
                "binding_name": "value",
                "to_kind": "skill_input",
                "ref": name,
            }
            for name in ("supplier_name", "order_no")
        ]
        configured = transform_configuration(
            readiness,
            SkillConfigurationDraft.model_validate(
                {
                    "schema_version": "skill-configuration-draft/v0.1",
                    "skill": {
                        "name": "Purchase order acceptance",
                        "description": "Live recorded query, extraction, row selection and iframe acceptance.",
                    },
                    "inputs": [
                        {
                            "ref": name,
                            "title": name,
                            "value_type": "string",
                            "required": True,
                        }
                        for name in RECORDING
                    ],
                    "secrets": [],
                    "asset_inputs": [],
                    "outputs": [
                        {
                            "name": "acceptance_result",
                            "title": "Acceptance result",
                            "variable_ref": "acceptance_result",
                            "value_type": "string",
                        }
                    ],
                    "asset_outputs": [],
                    "binding_promotions": promotions,
                    "stage_2_rules": None,
                }
            ),
            skill_id="first-purchase-order-acceptance",
        )
        destination = evidence_dir / "compiled_skill"

        class CountingCompiler:
            def __init__(self) -> None:
                self.count = 0
                self.delegate = DeterministicCompiler()

            def compile(self, *args, **kwargs):
                self.count += 1
                return self.delegate.compile(*args, **kwargs)

        compiler = CountingCompiler()
        compiled = compiler.compile(
            configured.timeline,
            configured.skill_definition,
            destination,
        )
        if compiled.status != "published" or compiled.artifacts is None:
            raise RuntimeError("live_creation.compile_failed")
        corpus = "\n".join(compiled.artifacts.files.values())
        forbidden_values = {
            str(value)
            for profile in PROFILES.values()
            for source in (profile["inputs"], profile["order"])
            for value in source.values()
        }
        leaked = sorted(value for value in forbidden_values if value in corpus)
        if leaked:
            raise RuntimeError("live_creation.recorded_value_leaked")
        forbidden_fragments = (
            ".first(",
            ".nth(",
            "backend.rpa",
            "browser-use history",
            "token=",
            "about:blank",
        )
        if any(fragment in corpus.lower() for fragment in forbidden_fragments):
            raise RuntimeError("live_creation.forbidden_artifact_fragment")
        artifact_hash = hashlib.sha256(
            "".join(
                f"{name}\0{compiled.artifacts.files[name]}"
                for name in sorted(compiled.artifacts.files)
            ).encode()
        ).hexdigest()
        reports = (setup_report, extraction_report, form_report)
        evidence = {
            "producer": "playwright-manual-inputs",
            "agent_action_producer": "direct-actual-tool-action-fixture",
            "natural_language_agent_invoked": False,
            "browser_use_version_gate": "0.13.2",
            "manual_candidate_ids": dict(manual_candidates),
            "adapter_actual_actions": sum(
                report.actual_action_count for report in reports
            ),
            "candidate_ids": [
                candidate_id
                for report in reports
                for candidate_id in report.candidate_ids
            ],
            "non_sop": [
                item.action_name
                for report in reports
                for item in report.non_sop
            ],
            "pages": sorted(page_refs.values()),
            "frames": sorted(frame_refs.values()),
        }
        return _LiveCreationBuild(
            session=session,
            configured=configured,
            destination=destination,
            artifact_hash=artifact_hash,
            adapter_rounds=reports,
            compile_count=compiler.count,
            evidence=evidence,
        )
    finally:
        browser_session.detach()


async def _build_and_compile_live(
    evidence_dir: Path,
    *,
    page: object,
    context: object,
    cdp_url: str,
) -> _LiveCreationBuild:
    """Create through the production Browser-use Agent/Tools invocation boundary."""

    session = SkillCreationSession(
        session_id="first_vertical_live_creation",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=128,
        fact_ttl=timedelta(minutes=2),
    )
    page_refs: dict[int, str] = {id(page): "runtime_main"}
    frame_refs: dict[int, str] = {id(page.main_frame): "main_frame"}
    pages_by_ref: dict[str, object] = {"runtime_main": page}
    frames_by_ref: dict[str, object] = {"main_frame": page.main_frame}

    def page_runtime_ref(target: object) -> str:
        key = id(target)
        if key not in page_refs:
            page_refs[key] = (
                "runtime_popup"
                if "runtime_popup" not in pages_by_ref
                else f"runtime_page_{len(page_refs) + 1}"
            )
        runtime_ref = page_refs[key]
        pages_by_ref[runtime_ref] = target
        return runtime_ref

    def frame_runtime_ref(target: object) -> str:
        key = id(target)
        if key not in frame_refs:
            name = str(getattr(target, "name", ""))
            frame_refs[key] = (
                "acceptance_frame"
                if name == "acceptance-form" and "acceptance_frame" not in frames_by_ref
                else f"runtime_frame_{len(frame_refs) + 1}"
            )
        runtime_ref = frame_refs[key]
        frames_by_ref[runtime_ref] = target
        return runtime_ref

    port = PlaywrightBrowserSessionPort(
        context=context,
        main_page=page,
        main_page_runtime_ref="runtime_main",
        main_frame_runtime_ref="main_frame",
        page_runtime_ref=page_runtime_ref,
        frame_runtime_ref=frame_runtime_ref,
        frame_path=lambda _page_ref, frame_ref: (
            FRAME_PATH if frame_ref == "acceptance_frame" else ()
        ),
        page_main_frame_runtime_ref=lambda target: frame_runtime_ref(target.main_frame),
        active_page=lambda: context.pages[-1],
        browser_use_cdp_url=cdp_url,
    )
    original_validate_target = port.validate_semantic_target
    dynamic_target_names = {
        RECORDING["business_type"],
        PROFILES["A"]["order"]["supplier_name"],
        PROFILES["A"]["order"]["currency"],
        str(TARGET_LOCATORS["confirm-acceptance"]["name"]),
    }

    async def validate_target(**kwargs: object) -> int:
        target_hint = kwargs.get("target_hint")
        if (
            isinstance(target_hint, dict)
            and target_hint.get("name") in dynamic_target_names
        ):
            # Dynamic options must remain Agent actions; a recorded option label
            # is not a valid deterministic runtime locator.
            return 0
        return await original_validate_target(**kwargs)

    port.validate_semantic_target = validate_target  # type: ignore[method-assign]
    browser_session = BrowserSession(port=port, creation=session)
    browser_session.attach()
    hosted = SimpleNamespace(browser=browser_session, owner_id="live-e2e-owner")
    manual_candidates: dict[str, str] = {}
    models: list[_ScriptedBrowserUseModel] = []

    async def manual_click(input_id: str, locator: object) -> str:
        x, y = await _manual_locator_point(locator)
        result = await browser_session.dispatch_manual_input(
            ManualInputCommand(input_id=input_id, kind="click", x=x, y=y)
        )
        if not result.candidate_id:
            raise RuntimeError("live_creation.manual_candidate_missing")
        return result.candidate_id

    async def manual_fill(name: str, value: str) -> str:
        locator = _playwright_locator(page, TARGET_LOCATORS[f"query-{name}"])
        candidate_id = await manual_click(f"live_focus_{name}", locator)
        result = await browser_session.dispatch_manual_input(
            ManualInputCommand(input_id=f"live_text_{name}", kind="text", text=value)
        )
        if result.candidate_id != candidate_id:
            raise RuntimeError("live_creation.manual_fill_candidate_changed")
        manual_candidates[name] = candidate_id
        return candidate_id

    async def invoke(
        instruction: str,
        steps: list[dict[str, object]],
        *,
        allowed_inputs: dict[str, str] | None = None,
        required_variable_refs: list[str] | None = None,
    ):
        model = _ScriptedBrowserUseModel(steps)
        models.append(model)

        async def model_factory(_owner_id: str):
            return model

        report = await execute_browser_use_instruction(
            hosted,
            AgentInstructionRequest(
                instruction=instruction,
                business_terms=["purchase order", "acceptance registration"],
                required_variable_refs=required_variable_refs or [],
                allowed_inputs=allowed_inputs or {},
                allowed_secret_names=[],
                allowed_data_assets={},
                page_aliases={"system_a": "purchase orders", "system_b": "acceptance"},
            ),
            model_factory=model_factory,
            agent_factory=_live_agent_factory,
        )
        if not model.complete:
            raise RuntimeError("live_creation.scripted_model_plan_incomplete")
        if report.invocation_count != report.actual_action_count + len(report.blocked):
            raise RuntimeError("live_creation.action_accounting_incomplete")
        if report.blocked:
            raise RuntimeError("live_creation.browser_use_action_blocked")
        return report

    try:
        await manual_fill("supplier_name", RECORDING["supplier_name"])
        await manual_fill("order_no", RECORDING["order_no"])
        browser_session.enter_agent_control(at=datetime.now(timezone.utc))
        setup_report = await invoke(
            "Use the allowed business type and date inputs to complete the open query controls.",
            [
                {
                    "action": "click",
                    "index_marker": str(TARGET_LOCATORS["business-type"]["name"]),
                },
                {"action": "wait", "params": {"seconds": 1}},
                {
                    "action": "click_allowed_input",
                    "index_marker": RECORDING["business_type"],
                    "params": {"input_ref": "business_type"},
                },
                {
                    "action": "input_literal",
                    "index_marker": "date-from",
                    "params": {"text": RECORDING["date_from"]},
                },
                {
                    "action": "input_literal",
                    "index_marker": "date-to",
                    "params": {"text": RECORDING["date_to"]},
                },
                {"action": "done", "params": {"text": "Query controls set", "success": True}},
            ],
            allowed_inputs={
                "business_type": RECORDING["business_type"],
                "date_from": RECORDING["date_from"],
                "date_to": RECORDING["date_to"],
            },
        )
        if len(setup_report.candidate_ids) != 4:
            raise RuntimeError("live_creation.setup_action_count_invalid")

        session.switch_control(ControlMode.HUMAN, at=datetime.now(timezone.utc))
        manual_candidates["query_submit"] = await manual_click(
            "live_query_submit",
            _playwright_locator(page, TARGET_LOCATORS["query-submit"]),
        )
        await page.get_by_role("row").filter(
            has_text=RECORDING["order_no"]
        ).wait_for(state="visible")
        browser_session.enter_agent_control(at=datetime.now(timezone.utc))
        extraction_report = await invoke(
            "Read the matching order into purchase_order and open its acceptance page by order number.",
            [
                {
                    "action": "extract_variable",
                    "observe_all": list(PROFILES["A"]["order"].values()),
                    "params": {
                        "variable_ref": "purchase_order",
                        "value": PROFILES["A"]["order"],
                        "input_refs": ["order_no"],
                    },
                },
                {
                    "action": "click_variable",
                    "index_marker": "<button",
                    "after": RECORDING["order_no"],
                    "params": {"variable_ref": "purchase_order.order_no"},
                },
                {"action": "done", "params": {"text": "Acceptance page opened", "success": True}},
            ],
            allowed_inputs={"order_no": RECORDING["order_no"]},
        )
        await browser_session.drain_pending_facts(timeout=5)
        popup = context.pages[-1]
        if popup is page or session.pages.resolve(page_runtime_ref(popup)) != "page_001":
            raise RuntimeError("live_creation.popup_page_not_registered")
        frame_title = str(FRAME_PATH[0]["locators"][0]["value"])
        await popup.get_by_title(frame_title, exact=True).wait_for(state="visible")
        acceptance_frame = popup.frame(name="acceptance-form")
        if acceptance_frame is None:
            raise RuntimeError("live_creation.acceptance_frame_missing")
        frame_runtime_ref(acceptance_frame)

        field_steps = [
            ("source-order-no", "purchase_order.order_no"),
            ("supplier-search", "purchase_order.supplier_name"),
            ("contract-no", "purchase_order.contract_no"),
            ("acceptance-amount", "purchase_order.amount"),
            ("order-date", "purchase_order.order_date"),
        ]
        form_steps: list[dict[str, object]] = [
            {
                "action": "input_variable",
                "index_marker": marker,
                "params": {"variable_ref": variable_ref},
            }
            for marker, variable_ref in field_steps
        ]
        form_steps.extend(
            [
                {
                    "action": "click_variable",
                    "index_marker": str(PROFILES["A"]["order"]["supplier_name"]),
                    "params": {"variable_ref": "purchase_order.supplier_name"},
                },
                {
                    "action": "click",
                    "index_marker": str(TARGET_LOCATORS["currency"]["name"]),
                },
                {
                    "action": "click_variable",
                    "index_marker": str(PROFILES["A"]["order"]["currency"]),
                    "params": {"variable_ref": "purchase_order.currency"},
                },
                {
                    "action": "input_literal",
                    "index_marker": "acceptance-description",
                    "params": {"text": "\u81ea\u52a8\u521b\u5efa"},
                },
                {"action": "click", "index_marker": "acceptance-confirmed"},
                {
                    "action": "click",
                    "index_marker": str(TARGET_LOCATORS["save-acceptance"]["name"]),
                },
                {
                    "action": "click",
                    "index_marker": str(TARGET_LOCATORS["confirm-acceptance"]["name"]),
                },
                {
                    "action": "extract_variable",
                    "observe": "\u9a8c\u6536\u767b\u8bb0\u5df2\u4fdd\u5b58",
                    "value_from_observation": "\u9a8c\u6536\u767b\u8bb0\u5df2\u4fdd\u5b58",
                    "params": {
                        "variable_ref": "acceptance_result",
                    },
                },
                {"action": "done", "params": {"text": "Acceptance submitted", "success": True}},
            ]
        )
        form_report = await invoke(
            "Fill the iframe from purchase_order, submit acceptance, and read the saved result.",
            form_steps,
            required_variable_refs=[
                "purchase_order.order_no",
                "purchase_order.supplier_name",
                "purchase_order.contract_no",
                "purchase_order.amount",
                "purchase_order.currency",
                "purchase_order.order_date",
            ],
        )
        await browser_session.drain_pending_facts(timeout=5)

        for candidate_id, candidate in session.candidates.items():
            if candidate_id in session.accepted_traces or candidate_id in session.diagnostics:
                continue
            outcome = session.settle_candidate(
                candidate_id,
                scope=BrowserScope.model_validate(
                    candidate.scope_hint.model_dump(exclude_none=True)
                ),
            )
            if getattr(outcome, "status", None) != "accepted":
                raise RuntimeError(f"live_creation.settlement_failed:{candidate_id}")
        readiness = session.build_readiness()
        if not readiness.ready or readiness.issues:
            raise RuntimeError("live_creation.build_not_ready")

        setup_ids = setup_report.candidate_ids
        promotions = [
            {
                "trace_id": session.accepted_traces[manual_candidates[name]].trace_id,
                "binding_name": "value",
                "to_kind": "skill_input",
                "ref": name,
            }
            for name in ("supplier_name", "order_no")
        ]
        promotions.extend(
            [
                {
                    "trace_id": session.accepted_traces[setup_ids[2]].trace_id,
                    "binding_name": "value",
                    "to_kind": "skill_input",
                    "ref": "date_from",
                },
                {
                    "trace_id": session.accepted_traces[setup_ids[3]].trace_id,
                    "binding_name": "value",
                    "to_kind": "skill_input",
                    "ref": "date_to",
                },
            ]
        )
        configured = transform_configuration(
            readiness,
            SkillConfigurationDraft.model_validate(
                {
                    "schema_version": "skill-configuration-draft/v0.1",
                    "skill": {
                        "name": "Purchase order acceptance",
                        "description": "Live Agent/Tools recorded purchase-order acceptance.",
                    },
                    "inputs": [
                        {
                            "ref": name,
                            "title": name,
                            "value_type": "string",
                            "required": True,
                        }
                        for name in RECORDING
                    ],
                    "secrets": [],
                    "asset_inputs": [],
                    "outputs": [
                        {
                            "name": "acceptance_result",
                            "title": "Acceptance result",
                            "variable_ref": "acceptance_result",
                            "value_type": "string",
                        }
                    ],
                    "asset_outputs": [],
                    "binding_promotions": promotions,
                    "stage_2_rules": None,
                }
            ),
            skill_id="first-purchase-order-acceptance",
        )
        destination = evidence_dir / "compiled_skill"

        class CountingCompiler:
            def __init__(self) -> None:
                self.count = 0
                self.delegate = DeterministicCompiler()

            def compile(self, *args, **kwargs):
                self.count += 1
                return self.delegate.compile(*args, **kwargs)

        compiler = CountingCompiler()
        compiled = compiler.compile(
            configured.timeline, configured.skill_definition, destination
        )
        if compiled.status != "published" or compiled.artifacts is None:
            raise RuntimeError("live_creation.compile_failed")
        corpus = "\n".join(compiled.artifacts.files.values())
        forbidden_values = {
            str(value)
            for profile in PROFILES.values()
            for source in (profile["inputs"], profile["order"])
            for value in source.values()
        }
        if any(value in corpus for value in forbidden_values):
            raise RuntimeError("live_creation.recorded_value_leaked")
        if (
            "inputs={'input.order_no': ctx.inputs.require('order_no')}"
            not in corpus
        ):
            raise RuntimeError("live_creation.extract_input_binding_not_compiled")
        for fragment in (".first(", ".nth(", "backend.rpa", "token=", "about:blank"):
            if fragment in corpus.lower():
                raise RuntimeError("live_creation.forbidden_artifact_fragment")
        artifact_hash = hashlib.sha256(
            "".join(
                f"{name}\0{compiled.artifacts.files[name]}"
                for name in sorted(compiled.artifacts.files)
            ).encode()
        ).hexdigest()
        reports = (setup_report, extraction_report, form_report)
        invocation_count = sum(report.invocation_count for report in reports)
        adapter_actions = sum(report.actual_action_count for report in reports)
        blocked_count = sum(len(report.blocked) for report in reports)
        if invocation_count != adapter_actions + blocked_count:
            raise RuntimeError("live_creation.action_accounting_incomplete")
        evidence = {
            "producer": "playwright-manual-inputs",
            "agent_action_producer": "production-browser-use-executor",
            "executor": "rpa_agent.host.browser_use_agent.execute_browser_use_instruction",
            "agent_factory": "browser_use.Agent",
            "tools": "RecordingBrowserUseTools.act",
            "natural_language_agent_invoked": True,
            "browser_use_version_gate": "0.13.2",
            "scripted_model_invocations": sum(model.invocation_count for model in models),
            "invocation_count": invocation_count,
            "adapter_actual_actions": adapter_actions,
            "blocked_count": blocked_count,
            "manual_candidate_ids": dict(manual_candidates),
            "candidate_ids": [
                candidate_id for report in reports for candidate_id in report.candidate_ids
            ],
            "non_sop": [
                item.action_name for report in reports for item in report.non_sop
            ],
            "pages": sorted(pages_by_ref),
            "frames": sorted(frames_by_ref),
        }
        return _LiveCreationBuild(
            session=session,
            configured=configured,
            destination=destination,
            artifact_hash=artifact_hash,
            adapter_rounds=reports,
            compile_count=compiler.count,
            evidence=evidence,
        )
    finally:
        browser_session.detach()


class _Locator:
    created: list["_Locator"] = []

    def __init__(self, count: int = 1, *, on_fill=None, on_click=None, on_select=None, on_text=None, frame=None, children=None, filter_factory=None):
        self._count, self._on_fill, self._on_click, self._on_select, self._on_text = count, on_fill, on_click, on_select, on_text
        self.content_frame, self._children, self._filter_factory = frame, children or {}, filter_factory
        self.nth_calls: list[int] = []
        self.created.append(self)
    async def count(self): return self._count
    def filter(self, *, has_text: str): return self._filter_factory(has_text) if self._filter_factory else _Locator(0)
    def get_by_role(self, role: str, *, name=None, exact=True): return self._children.get(("role", role, name), _Locator(0))
    def get_by_test_id(self, value: str): return self._children.get(("test_id", value), _Locator(0))
    def locator(self, value: str): return self._children.get(("selector", value), _Locator(0))
    async def fill(self, value: str):
        if self._on_fill: self._on_fill(value)
    async def click(self):
        if self._on_click: self._on_click()
    async def evaluate(self, script: str): return [{"value": "CNY", "label": "CNY"}, {"value": "USD", "label": "USD"}]
    async def select_option(self, **kwargs):
        if self._on_select: self._on_select(next(iter(kwargs.values())))
        return [next(iter(kwargs.values()))]
    async def inner_text(self): return self._on_text() if self._on_text else "accepted"
    def nth(self, index: int): self.nth_calls.append(index); return _Locator(0)


class _Scope(_Locator):
    url = "https://eval.invalid/ready"
    def get_by_label(self, value: str, *, exact=True): return self._children.get(("label", value), _Locator(0))
    def get_by_placeholder(self, value: str, *, exact=True): return self._children.get(("placeholder", value), _Locator(0))
    def get_by_text(self, value: str, *, exact=True): return self._children.get(("text", value), _Locator(0))
    def get_by_title(self, value: str, *, exact=True): return self._children.get(("title", value), _Locator(0))
    def get_by_alt_text(self, value: str, *, exact=True): return self._children.get(("alt_text", value), _Locator(0))
    def locator(self, value: str): return self._children.get(("selector", value), _Locator(0))
    def expect_navigation(self): return _Event(self)
    async def wait_for_url(self, matcher):
        assert matcher(self.url)
    async def wait_for_load_state(self, _state: str): return None


class _Event:
    def __init__(self, value): self._value = value
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return None
    @property
    async def value(self): return self._value


@dataclass
class _OfflineOracle:
    profile: str
    target_position: int
    selected_position: int | None = None
    selected_order_no: str | None = None
    draft: dict[str, Any] | None = None
    record: dict[str, Any] | None = None

    def evaluate(self) -> dict[str, Any]:
        expected = {**PROFILES[self.profile]["order"], "description": "自动创建", "confirmed": True}
        mismatches = []
        if self.selected_position != self.target_position: mismatches.append("target_order")
        if self.record is None: mismatches.append("record_count")
        else: mismatches.extend(key for key, value in expected.items() if self.record.get(key) != value)
        return {"passed": not mismatches, "profile": self.profile, "record_count": 1 if self.record else 0, "mismatches": mismatches, "target_order_no": expected["order_no"], "selected_order_no": self.selected_order_no}


def _browser(oracle: _OfflineOracle):
    oracle.draft = {}
    form_children: dict[tuple[Any, ...], _Locator] = {}
    def fill(name): return lambda value: oracle.draft.__setitem__(name, value)
    for name, test_id in (("order_no", "order-no"), ("supplier_name", "supplier-name"), ("contract_no", "contract-no"), ("amount", "amount"), ("order_date", "order-date"), ("description", "description")):
        form_children[("label", TARGET_LOCATORS[test_id]["value"])] = _Locator(on_fill=fill(name))
    form_children[("role", "combobox", "币种")] = _Locator()
    form_children[("label", "已核对以上信息并确认无误")] = _Locator(on_click=lambda: oracle.draft.__setitem__("confirmed", True))
    form_children[("role", "button", "保存")] = _Locator()
    form_children[("role", "button", "确认提交")] = _Locator(on_click=lambda: setattr(oracle, "record", dict(oracle.draft)))
    form_children[("selector", "[role='status'].success")] = _Locator(on_text=lambda: "accepted")
    def option_filter(value: str):
        field = "currency" if value in {"CNY", "USD", "EUR", "GBP"} else "supplier_name"
        return _Locator(children={("role", "button", None): _Locator(on_click=lambda: oracle.draft.__setitem__(field, value))})
    form_children[("role", "option", None)] = _Locator(count=4, filter_factory=option_filter)
    frame = _Scope(children=form_children)
    popup = _Scope(children={("title", "验收登记表单"): _Locator(frame=frame)})

    def row_filter(order_no: str):
        position = oracle.target_position if order_no == PROFILES[oracle.profile]["order"]["order_no"] else -1
        if position < 0: return _Locator(0)
        def select(): oracle.selected_position, oracle.selected_order_no = position, order_no
        return _Locator(children={("role", "button", None): _Locator(on_click=select)})
    rows = _Locator(count=3, filter_factory=row_filter)
    main = _Scope(children={("role", "row", None): rows})
    for name in RECORDING:
        if name != "business_type":
            main._children[("label", TARGET_LOCATORS[f"query-{name}"]["value"])] = _Locator()
    main._children[("role", "combobox", "业务类型")] = _Locator()
    main._children[("role", "button", "查询")] = _Locator()
    main._children[("role", "option", None)] = _Locator(count=4, filter_factory=lambda value: _Locator(children={("role", "button", None): _Locator()}))
    main.context = type("Context", (), {"expect_page": lambda self: _Event(popup)})()
    return main


def _load_skill(destination: Path, package_name: str):
    try:
        package = ModuleType(package_name); package.__path__ = [str(destination)]; sys.modules[package_name] = package
        for module_name in ("browser_segment", "skill"):
            spec = importlib.util.spec_from_file_location(f"{package_name}.{module_name}", destination / f"{module_name}.py")
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
        return sys.modules[f"{package_name}.skill"]
    except BaseException:
        _cleanup_generated_package(package_name)
        raise


def _cleanup_generated_package(package_name: str) -> None:
    for name in (
        f"{package_name}.skill",
        f"{package_name}.browser_segment",
        package_name,
    ):
        sys.modules.pop(name, None)


def _record_live_failure(
    replay: dict[str, Any],
    exc: BaseException,
    *,
    secrets: tuple[str, ...],
    pages: list[str] | None = None,
) -> None:
    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
        raise exc
    replay.update(
        {
            "status": "failed",
            "failure": {
                "type": type(exc).__name__,
                "phase": getattr(exc, "phase", None),
                "code": getattr(exc, "code", None),
                "trace_id": getattr(exc, "trace_id", None),
                "message": _safe_failure_message(exc, secrets=secrets),
            },
            "pages": list(pages or ()),
        }
    )


def _note_cleanup_failure(primary: BaseException) -> None:
    note = "live_replay.cleanup_failed"
    if note not in getattr(primary, "__notes__", ()):
        primary.add_note(note)


async def _close_live_resource(
    resource: object,
    *,
    primary: BaseException | None = None,
) -> None:
    cleanup_error: BaseException | None = None
    try:
        await resource.close()
    except BaseException as exc:
        cleanup_error = exc
    if cleanup_error is None:
        return
    if primary is not None:
        _note_cleanup_failure(primary)
        return
    if isinstance(cleanup_error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
        raise cleanup_error
    raise RuntimeError("live_replay.cleanup_failed")


async def _cleanup_live_profile(
    context: object,
    package_name: str,
    *,
    primary: BaseException | None = None,
) -> None:
    _cleanup_generated_package(package_name)
    await _close_live_resource(context, primary=primary)


async def _cleanup_live_browser(
    browser: object,
    *,
    primary: BaseException | None = None,
) -> None:
    await _close_live_resource(browser, primary=primary)


async def run_offline_replay(evidence_dir: Path) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    session, configured, destination, artifact_hash, extract_report, form_report, compile_count = await _build_and_compile(evidence_dir)
    replays = []
    for profile in ("A", "B"):
        locator_start = len(_Locator.created)
        oracle = _OfflineOracle(profile=profile, target_position=PROFILES[profile]["target_position"])
        package_name = f"generated_first_skill_{profile.lower()}"
        module = _load_skill(destination, package_name)
        try:
            async def agent_backend(**kwargs):
                assert kwargs["output_names"] == ("purchase_order",)
                return {"purchase_order": dict(PROFILES[profile]["order"])}
            async def secret_provider(_ref: str): return None
            ctx = RunContext(run_id=f"replay-{profile.lower()}", definition=configured.skill_definition, main_page=_browser(oracle), input_values=PROFILES[profile]["inputs"], secret_provider=secret_provider, agent_backend=agent_backend)
            result = await module.execute_skill(ctx)
            summary = oracle.evaluate()
            assert result.status == "succeeded" and summary["passed"], (result, summary)
            assert not any(locator.nth_calls for locator in _Locator.created[locator_start:])
            replays.append({"profile": profile, "run_id": ctx.run_id, "artifact_hash": artifact_hash, "step_count": len(result.steps), "oracle": summary, "page_ref": "page_001", "frame": "acceptance-frame"})
        finally:
            _cleanup_generated_package(package_name)
    report = {
        "compile_count": compile_count,
        "artifact_hash": artifact_hash,
        "creation": {
            "candidate_count": len(session.candidates),
            "accepted_count": len(session.accepted_traces),
            "pending": False,
            "browser_rounds": [
                {"actual_actions": extract_report.actual_action_count, "candidate_ids": list(extract_report.candidate_ids)},
                {"actual_actions": form_report.actual_action_count, "candidate_ids": list(form_report.candidate_ids), "non_sop": [item.action_name for item in form_report.non_sop]},
            ],
            "trace_count": len(configured.timeline.traces),
        },
        "replays": replays,
    }
    (evidence_dir / "offline-replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _safe_page_path(path: str) -> str:
    path = re.sub(
        r"^/system-b/acceptance-frame/[^/]+$",
        "/system-b/acceptance-frame/{task_id}",
        path,
    )
    return re.sub(
        r"^/system-b/acceptance/[^/]+$",
        "/system-b/acceptance/{task_id}",
        path,
    )


def _safe_failure_message(exc: BaseException, *, secrets: tuple[str, ...]) -> str:
    message = getattr(exc, "safe_message", None)
    if not isinstance(message, str) or not message:
        message = f"{type(exc).__name__}: live replay failed"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "<credential-redacted>")
    message = re.sub(r"(?i)(?:[?&]token=)[^&\s'\"]+", "<credential-redacted>", message)
    message = re.sub(r"https?://[^\s'\"]+", "<url-redacted>", message)
    return message[:240]


async def run_live_replay(
    evidence_dir: Path,
    *,
    frontend_url: str,
    backend_url: str,
    reset_token: str,
    oracle_token: str,
    headed: bool = False,
) -> dict[str, Any]:
    """Execute the generated four-file artifact against a running eval-app.

    This function never falls back to the offline Oracle. A missing browser,
    unreachable app, failed generated step, or hidden-Oracle rejection is a
    failed live report.
    """
    if not reset_token or not oracle_token:
        raise ValueError("live_replay.tokens_required")
    evals_dir = Path(__file__).resolve().parents[5] / "rpa-eval-app" / "evals"
    if str(evals_dir) not in sys.path:
        sys.path.insert(0, str(evals_dir))
    from eval_app_client import EvalAppClient
    from playwright.async_api import async_playwright
    from urllib.parse import urlsplit

    evidence_dir.mkdir(parents=True, exist_ok=True)
    client = EvalAppClient(backend_url)
    replays: list[dict[str, Any]] = []
    remote_debugging_port = _reserve_loopback_port()
    cdp_url = f"http://127.0.0.1:{remote_debugging_port}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=not headed,
            args=[f"--remote-debugging-port={remote_debugging_port}"],
        )
        browser_primary: BaseException | None = None
        try:
            recording_context = await browser.new_context()
            recording_primary: BaseException | None = None
            try:
                reset = await asyncio.to_thread(
                    client.reset_acceptance_profile,
                    "A",
                    reset_token,
                )
                if reset.profile != "A":
                    raise RuntimeError("live_creation.reset_profile_mismatch")
                recording_page = await recording_context.new_page()
                await recording_page.goto(
                    f"{frontend_url.rstrip('/')}/system-a/orders"
                )
                await recording_page.get_by_role(
                    "combobox",
                    name="业务类型",
                    exact=True,
                ).wait_for(state="visible")
                live_build = await _build_and_compile_live(
                    evidence_dir,
                    page=recording_page,
                    context=recording_context,
                    cdp_url=cdp_url,
                )
            except BaseException as exc:
                recording_primary = exc
                raise
            finally:
                await _cleanup_live_profile(
                    recording_context,
                    "live_creation_no_generated_package",
                    primary=recording_primary,
                )

            session = live_build.session
            configured = live_build.configured
            destination = live_build.destination
            artifact_hash = live_build.artifact_hash
            compile_count = live_build.compile_count
            for profile in ("A", "B"):
                replay: dict[str, Any] = {"profile": profile, "run_id": f"live-replay-{profile.lower()}", "artifact_hash": artifact_hash}
                context = await browser.new_context()
                package_name = f"generated_first_skill_live_{profile.lower()}"
                profile_primary: BaseException | None = None
                try:
                    page = await context.new_page()
                    reset = await asyncio.to_thread(client.reset_acceptance_profile, profile, reset_token)
                    if reset.profile != profile:
                        raise RuntimeError("live_replay.reset_profile_mismatch")
                    await page.goto(f"{frontend_url.rstrip('/')}/system-a/orders")
                    await page.get_by_role(
                        "combobox", name="业务类型", exact=True
                    ).wait_for(state="visible")
                    module = _load_skill(destination, package_name)

                    async def agent_backend(**kwargs):
                        output_names = kwargs["output_names"]
                        inputs = kwargs["inputs"]
                        scope = kwargs["scope"]
                        if output_names == ("result",):
                            required = kwargs["required_paths"].get("result", ())
                            if required:
                                if set(inputs) != {"input.order_no"}:
                                    raise RuntimeError(
                                        "live_replay.agent_extract_input_unknown"
                                    )
                                order_no = str(inputs["input.order_no"])
                                row = scope.get_by_role("row").filter(has_text=order_no)
                                if await row.count() != 1:
                                    raise RuntimeError("live_replay.agent_row_not_unique")
                                cells = await row.locator("td").all_inner_texts()
                                if len(cells) < 6:
                                    raise RuntimeError("live_replay.agent_row_shape_invalid")
                                payload = {
                                    "order_no": cells[0].strip(),
                                    "supplier_name": cells[1].strip(),
                                    "contract_no": cells[2].strip(),
                                    "amount": cells[3].strip(),
                                    "currency": cells[4].strip(),
                                    "order_date": cells[5].strip(),
                                }
                                for path in required:
                                    if path not in payload:
                                        raise RuntimeError("live_replay.agent_required_path_missing")
                                return {"result": payload}
                            status_scope = scope
                            if hasattr(scope, "main_frame"):
                                frame_spec = dict(FRAME_PATH[0]["locators"][0])
                                frame_element = _playwright_locator(scope, frame_spec)
                                if await frame_element.count() != 1:
                                    raise RuntimeError(
                                        "live_replay.agent_result_frame_not_unique"
                                    )
                                status_scope = getattr(
                                    frame_element, "content_frame", None
                                )
                                if callable(status_scope):
                                    status_scope = status_scope()
                                if inspect.isawaitable(status_scope):
                                    status_scope = await status_scope
                                if status_scope is None:
                                    raise RuntimeError(
                                        "live_replay.agent_result_frame_unavailable"
                                    )
                            status = status_scope.get_by_role("status")
                            await status.wait_for(state="visible", timeout=5_000)
                            if await status.count() != 1:
                                raise RuntimeError(
                                    "live_replay.agent_result_not_unique"
                                )
                            text = (await status.inner_text()).strip()
                            if "\u9a8c\u6536\u767b\u8bb0\u5df2\u4fdd\u5b58" not in text:
                                raise RuntimeError("live_replay.agent_result_not_observed")
                            return {"result": "\u9a8c\u6536\u767b\u8bb0\u5df2\u4fdd\u5b58"}
                        if output_names:
                            raise RuntimeError("live_replay.agent_contract_unknown")
                        if inputs:
                            if set(inputs) == {"value"}:
                                # The number input is intentionally retained as an
                                # Agent Action when its browser semantics cannot be
                                # converted reliably during creation. The live host
                                # still acts on the current replay DOM and value.
                                target = _playwright_locator(
                                    scope, TARGET_LOCATORS["amount"]
                                )
                                if await target.count() != 1:
                                    raise RuntimeError(
                                        "live_replay.agent_input_target_not_unique"
                                    )
                                await target.fill(str(inputs["value"]))
                                return {}
                            if set(inputs) != {"row_key"}:
                                raise RuntimeError("live_replay.agent_input_unknown")
                            value = str(inputs["row_key"])
                            if value.startswith("PO-"):
                                target = (
                                    scope.get_by_role("row")
                                    .filter(has_text=value)
                                    .get_by_role("button")
                                )
                            else:
                                target = scope.get_by_role(
                                    "option", name=value, exact=True
                                )
                            if await target.count() != 1:
                                raise RuntimeError("live_replay.agent_target_not_unique")
                            await target.click()
                            return {}
                        confirm = scope.get_by_role(
                            "button",
                            name=str(TARGET_LOCATORS["confirm-acceptance"]["name"]),
                            exact=True,
                        )
                        if await confirm.count() == 1:
                            await confirm.click()
                            return {}
                        checkbox = _playwright_locator(
                            scope, TARGET_LOCATORS["confirmed"]
                        )
                        if await checkbox.count() != 1:
                            raise RuntimeError(
                                "live_replay.agent_click_target_not_unique"
                            )
                        await checkbox.click()
                        return {}

                    async def secret_provider(_ref: str): return None
                    ctx = RunContext(
                        run_id=replay["run_id"],
                        definition=configured.skill_definition,
                        main_page=page,
                        input_values=PROFILES[profile]["inputs"],
                        secret_provider=secret_provider,
                        agent_backend=agent_backend,
                    )
                    result = await module.execute_skill(ctx)
                    pages = context.pages
                    task_id = next(
                        (
                            segment
                            for current in pages
                            for segment in urlsplit(current.url).path.split("/")
                            if segment.startswith("task-")
                        ),
                        None,
                    )
                    if task_id is None:
                        raise RuntimeError("live_replay.task_id_not_observed")
                    oracle = await asyncio.to_thread(client.acceptance_oracle, task_id, oracle_token)
                    replay.update(
                        {
                            "status": "passed" if oracle.passed else "failed",
                            "steps": [
                                {"trace_id": step.trace_id, "sequence": step.sequence, "action_kind": step.action_kind, "status": step.status}
                                for step in result.steps
                            ],
                            "pages": [_safe_page_path(urlsplit(current.url).path) for current in pages],
                            "frame": "验收登记表单",
                            "oracle": {
                                "passed": oracle.passed,
                                "profile": oracle.profile,
                                "record_count": oracle.record_count,
                                "mismatches": list(oracle.mismatches),
                                "target_order_no": oracle.target_order_no,
                                "selected_order_no": oracle.selected_order_no,
                            },
                        }
                    )
                except BaseException as exc:
                    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                        profile_primary = exc
                        raise
                    try:
                        _record_live_failure(
                            replay,
                            exc,
                            secrets=(reset_token, oracle_token),
                            pages=[
                                _safe_page_path(urlsplit(current.url).path)
                                for current in context.pages
                            ],
                        )
                    except BaseException as handler_exc:
                        profile_primary = handler_exc
                        raise
                finally:
                    await _cleanup_live_profile(
                        context,
                        package_name,
                        primary=profile_primary,
                    )
                replays.append(replay)
        except BaseException as exc:
            browser_primary = exc
            raise
        finally:
            await _cleanup_live_browser(browser, primary=browser_primary)
    report = {
        "evidence_kind": "live-playwright-hidden-oracle",
        "compile_count": compile_count,
        "artifact_hash": artifact_hash,
        "trace_count": len(configured.timeline.traces),
        "creation_candidate_count": len(session.candidates),
        "adapter_rounds": [
            {
                "adapter_actions": round_report.actual_action_count,
                "candidate_ids": list(round_report.candidate_ids),
                "non_sop": [item.action_name for item in round_report.non_sop],
            }
            for round_report in live_build.adapter_rounds
        ],
        "creation": {
            **live_build.evidence,
            "pending": False,
            "ready": session.build_readiness().ready,
            "candidate_count": len(session.candidates),
            "accepted_count": len(session.accepted_traces),
        },
        "replays": replays,
        "passed": len(replays) == 2 and all(item.get("status") == "passed" and item.get("oracle", {}).get("passed") for item in replays),
    }
    (evidence_dir / "live-replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--evidence-dir", type=Path, default=Path(__file__).resolve().parent / ".replay-evidence")
    parser.add_argument("--frontend-url", default=os.environ.get("RPA_EVAL_FRONTEND_URL", "http://127.0.0.1:5175"))
    parser.add_argument("--backend-url", default=os.environ.get("RPA_EVAL_BACKEND_URL", "http://127.0.0.1:8085"))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    if args.mode == "live":
        report = asyncio.run(
            run_live_replay(
                args.evidence_dir,
                frontend_url=args.frontend_url,
                backend_url=args.backend_url,
                reset_token=os.environ.get("RPA_EVAL_RESET_TOKEN", ""),
                oracle_token=os.environ.get("RPA_EVAL_ORACLE_TOKEN", ""),
                headed=args.headed,
            )
        )
        passed = bool(report["passed"])
    else:
        report = asyncio.run(run_offline_replay(args.evidence_dir))
        passed = all(item["oracle"]["passed"] for item in report["replays"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
