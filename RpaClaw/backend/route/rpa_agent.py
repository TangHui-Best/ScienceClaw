"""Greenfield RPA Agent creation API.

The route composes the new domain with narrow injected host capabilities.  It
does not import any legacy RPA trace/session/compiler type.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from backend.config import settings
from backend.rpa_agent.api.models import (
    AgentInstructionRequest,
    ManualEventRequest,
    ManualInputRequest,
    ManualReservationRequest,
    StartSessionRequest,
    StartSessionResponse,
    TestRunRequest,
)
from backend.rpa_agent.browser_use import RecordingRoundReport
from backend.rpa_agent.compiler import DeterministicCompiler
from backend.rpa_agent.configuration import (
    ConfigurationError,
    SkillConfigurationDraft,
    transform_configuration,
)
from backend.rpa_agent.creation import ControlMode, SkillCreationSession
from backend.rpa_agent.host import (
    BrowserSession,
    BrowserSessionPort,
    HostedSession,
    SessionState,
    SessionStore,
    ManualInputCommand,
    publish_compiled_skill,
)
from backend.rpa_agent.host.browser_use_agent import (
    execute_browser_use_instruction,
    run_compiled_skill_with_agent,
)
from backend.user.dependencies import User, require_user


_SESSION_ID = re.compile(r"^rca_[a-z0-9]{24}$")
_SENSITIVE_KEY = re.compile(r"(?i)(?:secret|token|password|passwd|pwd|credential|api[_-]?key)")
logger = logging.getLogger(__name__)

BrowserProvider = Callable[[str, str], Awaitable[BrowserSessionPort]]
AgentInstructionExecutor = Callable[
    [HostedSession, AgentInstructionRequest], Awaitable[RecordingRoundReport]
]
RuntimeRunner = Callable[[HostedSession, TestRunRequest], Awaitable[Mapping[str, Any]]]
Publisher = Callable[[HostedSession], Awaitable[Mapping[str, str]]]


def _css_attribute_string(value: str) -> str:
    escaped: list[str] = []
    for character in value:
        codepoint = ord(character)
        if character in {'"', "\\"}:
            escaped.append("\\" + character)
        elif codepoint == 0:
            raise ValueError("browser_host.frame_name_invalid")
        elif codepoint < 32 or codepoint == 127:
            escaped.append(f"\\{codepoint:x} ")
        else:
            escaped.append(character)
    return "".join(escaped)


async def _unavailable_browser(_owner_id: str, _browser_ref: str) -> BrowserSessionPort:
    raise RuntimeError("browser_host_unavailable")


async def _resolve_local_cdp_url(_browser_ref: str, _owner_id: str) -> str:
    from backend.runtime.local_cdp import local_cdp_connector

    return await local_cdp_connector.get_cdp_url()


async def _scienceclaw_browser_provider(
    owner_id: str, browser_ref: str
) -> BrowserSessionPort:
    """Reuse the generic ScienceClaw preview page without old RPA models."""

    from backend.browser_preview import browser_preview_registry
    from backend.runtime.ownership import user_owns_runtime_session
    from backend.rpa_agent.host import PlaywrightBrowserSessionPort

    if not await user_owns_runtime_session(browser_ref, owner_id):
        raise RuntimeError("browser_host_not_owned")
    from backend.rpa_agent.host.scienceclaw_browser import (
        acquire_browser_runtime_lease,
    )

    runtime_lease = await acquire_browser_runtime_lease(
        owner_id=owner_id,
        browser_ref=browser_ref,
        preview_registry=browser_preview_registry,
        isolated_context=True,
        resolve_cdp_url=(
            _resolve_local_cdp_url
            if settings.storage_backend.strip().lower() == "local"
            else None
        ),
    )
    page = runtime_lease.page
    context = getattr(page, "context", None)
    if context is None:
        await runtime_lease.aclose()
        raise RuntimeError("browser_host_context_unavailable")

    page_refs: dict[int, str] = {}
    pages_by_ref: dict[str, object] = {}
    frame_refs: dict[int, str] = {}
    frames_by_ref: dict[str, object] = {}

    def page_runtime_ref(target: object) -> str:
        key = id(target)
        if key not in page_refs:
            page_refs[key] = f"host_page_{len(page_refs) + 1:04d}"
        runtime_ref = page_refs[key]
        pages_by_ref[runtime_ref] = target
        return runtime_ref

    def frame_runtime_ref(target: object) -> str:
        key = id(target)
        if key not in frame_refs:
            frame_refs[key] = f"host_frame_{len(frame_refs) + 1:04d}"
        runtime_ref = frame_refs[key]
        frames_by_ref[runtime_ref] = target
        return runtime_ref

    main_page_ref = page_runtime_ref(page)
    main_frame = getattr(page, "main_frame", None)
    if main_frame is None:
        await runtime_lease.aclose()
        raise RuntimeError("browser_host_main_frame_unavailable")
    main_frame_ref = frame_runtime_ref(main_frame)

    def resolve_frame_path(
        runtime_page_ref: str, runtime_frame_ref: str
    ) -> tuple[Mapping[str, object], ...]:
        target_page = pages_by_ref.get(runtime_page_ref)
        target_frame = frames_by_ref.get(runtime_frame_ref)
        if target_page is None or target_frame is None:
            raise ValueError("browser_host.frame_path_not_registered")
        page_main_frame = getattr(target_page, "main_frame", None)
        if page_main_frame is None:
            raise ValueError("browser_host.main_frame_not_registered")
        if target_frame is page_main_frame:
            return ()
        frame_page = getattr(target_frame, "page", target_page)
        if frame_page is not target_page:
            raise ValueError("browser_host.frame_page_mismatch")

        reversed_steps: list[Mapping[str, object]] = []
        current = target_frame
        while current is not page_main_frame:
            parent = getattr(current, "parent_frame", None)
            if parent is None:
                raise ValueError("browser_host.frame_parent_chain_invalid")
            name = getattr(current, "name", "")
            if not isinstance(name, str) or not name:
                raise ValueError("browser_host.frame_locator_unavailable")
            reversed_steps.append(
                {
                    "name": name,
                    "locators": [
                        {
                            "strategy": "css",
                            "value": (
                                'iframe[name="'
                                + _css_attribute_string(name)
                                + '"]'
                            ),
                        }
                    ],
                }
            )
            current = parent
        return tuple(reversed(reversed_steps))

    return PlaywrightBrowserSessionPort(
        context=context,
        main_page=page,
        main_page_runtime_ref=main_page_ref,
        main_frame_runtime_ref=main_frame_ref,
        page_runtime_ref=page_runtime_ref,
        frame_runtime_ref=frame_runtime_ref,
        frame_path=resolve_frame_path,
        page_main_frame_runtime_ref=lambda target: frame_runtime_ref(
            getattr(target, "main_frame")
        ),
        active_page=lambda: (
            browser_preview_registry.get_active_page(browser_ref) or page
        ),
        browser_use_cdp_url=runtime_lease.cdp_url,
        cleanup=runtime_lease.aclose,
    )


@dataclass(slots=True)
class RpaAgentApiServices:
    artifact_root: Path
    browser_provider: BrowserProvider = _unavailable_browser
    agent_executor: AgentInstructionExecutor | None = None
    runtime_runner: RuntimeRunner | None = None
    publisher: Publisher | None = None
    compiler: DeterministicCompiler | None = None
    store: SessionStore | None = None
    browser_use_version: str = "0.13.2"

    def __post_init__(self) -> None:
        self.artifact_root = Path(self.artifact_root)
        if self.browser_use_version != "0.13.2":
            raise ValueError("rpa_agent.browser_use_version_unsupported")
        if self.compiler is None:
            self.compiler = DeterministicCompiler()
        if self.store is None:
            self.store = SessionStore(ttl=timedelta(hours=2))


class _SafeValidationRoute(APIRoute):
    """Do not mirror invalid bodies (especially Secret values) in 422 replies."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={"detail": {"code": "rpa_agent.request_invalid"}},
                )

        return safe_handler


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


def _owner(user: User) -> str:
    if not user.id:
        raise _error(401, "rpa_agent.unauthenticated")
    return user.id


def _require_new_session_id(session_id: str) -> None:
    if _SESSION_ID.fullmatch(session_id) is None:
        raise _error(404, "rpa_agent.session_not_found")


def _state_error(exc: ValueError) -> HTTPException:
    code = str(exc).split(":", 1)[0]
    if code == "api.state_conflict":
        return _error(409, "rpa_agent.state_conflict")
    if code == "api.artifact_changed":
        return _error(409, "rpa_agent.artifact_changed")
    if code.startswith("manual_reservation"):
        return _error(409, f"rpa_agent.{code}")
    if code.startswith("browser_session.pending_fact"):
        return _error(409, "rpa_agent.pending_browser_fact")
    if code.startswith("browser_session.agent_settlement"):
        return _error(422, "rpa_agent.agent_settlement_failed")
    return _error(422, "rpa_agent.operation_invalid")


_REQUIRED_ARTIFACT_FILES = frozenset(
    {"SKILL.md", "skill.manifest.json", "skill.py", "browser_segment.py"}
)


def _artifact_hash_from_disk(artifact_dir: Path) -> str:
    try:
        entries = {
            name: artifact_dir / name for name in _REQUIRED_ARTIFACT_FILES
        }
        if any(
            not entry.is_file() or entry.is_symlink()
            for entry in entries.values()
        ):
            raise ValueError("api.artifact_changed")
    except OSError as exc:
        raise ValueError("api.artifact_changed") from exc

    digest = hashlib.sha256()
    for name in sorted(entries):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(entries[name].read_bytes())
        except OSError as exc:
            raise ValueError("api.artifact_changed") from exc
        digest.update(b"\0")
    return digest.hexdigest()


def _require_artifact_unchanged(hosted: HostedSession) -> None:
    if hosted.artifact_hash is None:
        raise ValueError("api.compiled_artifact_missing")
    if _artifact_hash_from_disk(hosted.artifact_dir) != hosted.artifact_hash:
        raise ValueError("api.artifact_changed")


def _draft(creation: SkillCreationSession) -> SkillConfigurationDraft:
    asset_inputs: dict[str, dict[str, Any]] = {}
    asset_outputs: dict[str, dict[str, Any]] = {}
    for trace in sorted(
        creation.accepted_traces.values(), key=lambda item: item.sequence
    ):
        for binding in trace.data_bindings:
            if binding.kind != "data_asset":
                continue
            if binding.direction == "input":
                asset_inputs.setdefault(
                    binding.ref,
                    {
                        "ref": binding.ref,
                        "title": binding.ref,
                        "required": True,
                    },
                )
            else:
                asset_outputs.setdefault(
                    binding.name,
                    {
                        "name": binding.name,
                        "title": binding.ref,
                        "asset_ref": binding.ref,
                    },
                )
    return SkillConfigurationDraft.model_validate(
        {
            "schema_version": "skill-configuration-draft/v0.1",
            "skill": {
                "name": "未命名 SKILL",
                "description": "请在编译前补充 SKILL 说明",
            },
            "inputs": [],
            "secrets": [],
            "asset_inputs": list(asset_inputs.values()),
            "outputs": [],
            "asset_outputs": list(asset_outputs.values()),
            "binding_promotions": [],
        }
    )


def _configuration_options(
    creation: SkillCreationSession, draft: SkillConfigurationDraft
) -> dict[str, Any]:
    locations: list[dict[str, Any]] = []
    for trace in sorted(
        creation.accepted_traces.values(), key=lambda item: item.sequence
    ):
        for binding in trace.data_bindings:
            locations.append(
                {
                    "trace_id": trace.trace_id,
                    "binding_name": binding.name,
                    "direction": binding.direction,
                    "kind": binding.kind,
                    "ref": getattr(binding, "ref", None),
                    "sensitive": binding.sensitive,
                }
            )
    readiness = creation.build_readiness(
        external_asset_refs={item.ref for item in draft.asset_inputs}
    )
    return {
        "binding_locations": locations,
        "readiness": {
            "ready": readiness.ready,
            "issues": [
                {
                    **asdict(issue),
                    "code": issue.code.value,
                }
                for issue in readiness.issues
            ],
        },
    }


def _sanitize(value: Any, *, secret_values: frozenset[str] = frozenset()) -> Any:
    tokens = tuple(
        sorted(
            (secret for secret in secret_values if secret),
            key=len,
            reverse=True,
        )
    )
    return _sanitize_with_tokens(value, tokens=tokens)


def _redact_text(value: str, *, tokens: tuple[str, ...]) -> str:
    redacted = value
    for token in tokens:
        redacted = redacted.replace(token, "[REDACTED]")
    return redacted


def _sanitize_with_tokens(value: Any, *, tokens: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        return {
            _redact_text(str(key), tokens=tokens): (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else _sanitize_with_tokens(item, tokens=tokens)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_with_tokens(item, tokens=tokens) for item in value]
    if isinstance(value, str):
        return _redact_text(value, tokens=tokens)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return _redact_text(str(value), tokens=tokens)


def _report_payload(report: RecordingRoundReport) -> dict[str, Any]:
    return {
        "invocation_count": report.invocation_count,
        "actual_action_count": report.actual_action_count,
        "candidate_ids": list(report.candidate_ids),
        "non_sop": [asdict(item) for item in report.non_sop],
        "blocked": [asdict(item) for item in report.blocked],
        "agent_result": report.agent_result,
    }


def build_router(services: RpaAgentApiServices) -> APIRouter:
    router = APIRouter(tags=["RPA Agent"], route_class=_SafeValidationRoute)
    assert services.store is not None
    assert services.compiler is not None

    @router.post(
        "/sessions",
        status_code=status.HTTP_201_CREATED,
        response_model=StartSessionResponse,
    )
    async def start_session(
        body: StartSessionRequest,
        user: User = Depends(require_user),
    ):
        owner_id = _owner(user)
        try:
            port = await services.browser_provider(owner_id, body.browser_session_ref)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except BaseException as exc:
            logger.error(
                "rpa_agent browser host unavailable storage_backend=%s error_type=%s",
                settings.storage_backend,
                type(exc).__name__,
            )
            raise _error(503, "rpa_agent.browser_host_unavailable") from None
        creation = SkillCreationSession(
            session_id="creation_" + hashlib.sha256(os.urandom(32)).hexdigest()[:16],
            main_runtime_ref=port.main_page_runtime_ref,
            fact_buffer_capacity=256,
            fact_ttl=timedelta(seconds=30),
        )
        browser = BrowserSession(port=port, creation=creation)
        try:
            browser.attach()
            hosted = await services.store.create(
                owner_id=owner_id,
                browser_session_ref=body.browser_session_ref,
                browser=browser,
                artifact_dir=services.artifact_root,
            )
        except BaseException as primary:
            await browser.aclose(
                at=datetime.now(timezone.utc),
                primary=primary,
            )
            raise
        return StartSessionResponse.model_validate(
            {
                "session_id": hosted.session_id,
                "state": hosted.state.value,
                "main_scope": {
                    "page_runtime_ref": port.main_page_runtime_ref,
                    "frame_runtime_ref": port.main_frame_runtime_ref,
                },
            }
        )

    @router.post(
        "/sessions/{session_id}/manual-reservations",
        status_code=status.HTTP_201_CREATED,
    )
    async def reserve_manual(
        session_id: str,
        body: ManualReservationRequest,
        user: User = Depends(require_user),
    ):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.RECORDING)
                token = hosted.browser.reserve_manual(
                    candidate_id=body.candidate_id,
                    page_runtime_ref=body.page_runtime_ref,
                    frame_runtime_ref=body.frame_runtime_ref,
                )
                return {"reservation_token": token}
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.post("/sessions/{session_id}/manual-events")
    async def manual_event(
        session_id: str,
        body: ManualEventRequest,
        user: User = Depends(require_user),
    ):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.RECORDING)
                event = hosted.browser.manual_event_from_payload(body)
                candidate_ids = hosted.browser.ingest_manual(
                    token=body.reservation_token,
                    event=event,
                    finish=body.finish,
                )
                return {"candidate_ids": list(candidate_ids)}
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.post("/sessions/{session_id}/manual-inputs")
    async def manual_input(
        session_id: str,
        body: ManualInputRequest,
        user: User = Depends(require_user),
    ):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.RECORDING)
                result = await hosted.browser.dispatch_manual_input(
                    ManualInputCommand(
                        input_id=body.input_id,
                        kind=body.kind,
                        x=body.x,
                        y=body.y,
                        text=body.text,
                    )
                )
                return {
                    "input_id": result.input_id,
                    "candidate_id": result.candidate_id,
                    "candidate_ids": list(result.candidate_ids),
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except RuntimeError:
            raise _error(503, "rpa_agent.manual_input_unavailable") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.post("/sessions/{session_id}/agent-instructions")
    async def agent_instruction(
        session_id: str,
        body: AgentInstructionRequest,
        user: User = Depends(require_user),
    ):
        _require_new_session_id(session_id)
        if services.agent_executor is None:
            raise _error(503, "rpa_agent.agent_unavailable")
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.RECORDING)
                now = datetime.now(timezone.utc)
                hosted.browser.enter_agent_control(at=now)
                primary: BaseException | None = None
                try:
                    report = await services.agent_executor(hosted, body)
                    if not isinstance(report, RecordingRoundReport):
                        raise ValueError("agent_executor.report_invalid")
                    await hosted.browser.drain_pending_facts(timeout=30)
                    settlement = hosted.browser.settle_agent_round(
                        report.candidate_ids
                    )
                    if settlement.pending_ids:
                        raise ValueError(
                            "browser_session.agent_settlement_incomplete:"
                            + ",".join(settlement.pending_ids)
                        )
                    if settlement.rejected_ids:
                        raise ValueError(
                            "browser_session.agent_settlement_rejected:"
                            + ",".join(settlement.rejected_ids)
                        )
                    payload = _report_payload(report)
                    payload["replayable_action_count"] = len(
                        settlement.accepted_ids
                    )
                    return payload
                except BaseException as exc:
                    primary = exc
                    raise
                finally:
                    try:
                        hosted.browser.creation.switch_control(
                            ControlMode.HUMAN, at=datetime.now(timezone.utc)
                        )
                    except BaseException:
                        if primary is None:
                            raise
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except RuntimeError:
            raise _error(503, "rpa_agent.agent_execution_unavailable") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.get("/sessions/{session_id}/projection")
    async def projection(session_id: str, user: User = Depends(require_user)):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                steps = hosted.browser.creation.creation_projection()
                return {
                    "state": hosted.state.value,
                    "steps": [
                        {
                            **asdict(item),
                            "status": item.status.value,
                        }
                        for item in steps
                    ],
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None

    @router.post("/sessions/{session_id}/stop")
    async def stop_session(session_id: str, user: User = Depends(require_user)):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.RECORDING)
                now = datetime.now(timezone.utc)
                await hosted.browser.drain_pending_facts(timeout=30)
                hosted.browser.finalize_recording(at=now)
                creation_steps = hosted.browser.creation.creation_projection()
                hosted.configuration_draft = _draft(hosted.browser.creation)
                hosted.state = SessionState.STOPPED
                try:
                    await hosted.browser.release_browser()
                except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                    raise
                except BaseException as exc:
                    hosted.cleanup_errors.append(type(exc).__name__)
                    logger.warning(
                        "rpa_agent recording browser cleanup failed error_type=%s",
                        type(exc).__name__,
                    )
                return {
                    "state": hosted.state.value,
                    "configuration_draft": hosted.configuration_draft.model_dump(
                        mode="json", exclude_unset=True
                    ),
                    "configuration_options": _configuration_options(
                        hosted.browser.creation, hosted.configuration_draft
                    ),
                    "creation_steps": [
                        {
                            **asdict(item),
                            "status": item.status.value,
                        }
                        for item in creation_steps
                    ],
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.delete("/sessions/{session_id}")
    async def discard_session(
        session_id: str,
        user: User = Depends(require_user),
    ):
        _require_new_session_id(session_id)
        removed = await services.store.discard(session_id, owner_id=_owner(user))
        if not removed:
            raise _error(404, "rpa_agent.session_not_found")
        return {"state": "discarded"}

    @router.put("/sessions/{session_id}/configuration")
    async def apply_configuration(
        session_id: str,
        body: SkillConfigurationDraft,
        user: User = Depends(require_user),
    ):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.STOPPED)
                readiness = hosted.browser.creation.build_readiness(
                    external_asset_refs={item.ref for item in body.asset_inputs}
                )
                hosted.configuration = transform_configuration(
                    readiness,
                    body,
                    skill_id="skill_" + hosted.session_id[4:],
                )
                hosted.configuration_draft = SkillConfigurationDraft.model_validate(
                    body.model_dump(mode="python", exclude_unset=True)
                )
                hosted.state = SessionState.CONFIGURED
                return {
                    "state": hosted.state.value,
                    "skill_definition": hosted.configuration.skill_definition.model_dump(
                        mode="json", exclude_unset=True
                    ),
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except (ValueError, ConfigurationError) as exc:
            raise _state_error(exc) from None

    @router.post("/sessions/{session_id}/compile")
    async def compile_skill(session_id: str, user: User = Depends(require_user)):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.CONFIGURED)
                assert hosted.configuration is not None
                result = services.compiler.compile(
                    hosted.configuration.timeline,
                    hosted.configuration.skill_definition,
                    hosted.artifact_dir,
                )
                if result.status != "published" or result.artifacts is None:
                    raise _error(422, "rpa_agent.compile_rejected")
                if set(result.artifacts.files) != _REQUIRED_ARTIFACT_FILES:
                    raise _error(422, "rpa_agent.compile_rejected")
                hosted.compile_result = result
                hosted.artifact_hash = _artifact_hash_from_disk(hosted.artifact_dir)
                hosted.state = SessionState.COMPILED
                return {
                    "state": hosted.state.value,
                    "artifact_files": sorted(result.artifacts.files),
                    "artifact_hash": hosted.artifact_hash,
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.post("/sessions/{session_id}/test-run")
    async def test_run(
        session_id: str,
        body: TestRunRequest,
        user: User = Depends(require_user),
    ):
        _require_new_session_id(session_id)
        if services.runtime_runner is None:
            raise _error(503, "rpa_agent.runtime_unavailable")
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.COMPILED)
                if hosted.compile_result is None or hosted.artifact_hash is None:
                    raise ValueError("api.compiled_artifact_missing")
                _require_artifact_unchanged(hosted)
                raw = await services.runtime_runner(hosted, body)
                _require_artifact_unchanged(hosted)
                if not isinstance(raw, Mapping):
                    raise ValueError("api.run_result_invalid")
                secret_values = frozenset(body.secrets.values())
                result = _sanitize(dict(raw), secret_values=secret_values)
                hosted.run_result = result
                hosted.test_passed = result.get("status") == "succeeded"
                if hosted.test_passed:
                    hosted.state = SessionState.TESTED
                return {
                    "state": hosted.state.value,
                    "artifact_hash": hosted.artifact_hash,
                    "run_result": result,
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.post("/sessions/{session_id}/save")
    async def save_skill(session_id: str, user: User = Depends(require_user)):
        _require_new_session_id(session_id)
        if services.publisher is None:
            raise _error(503, "rpa_agent.publisher_unavailable")
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.TESTED)
                if not hosted.test_passed or hosted.artifact_hash is None:
                    raise ValueError("api.test_success_required")
                _require_artifact_unchanged(hosted)
                published = await services.publisher(hosted)
                skill_ref = published.get("skill_ref") if isinstance(published, Mapping) else None
                if not isinstance(skill_ref, str) or not skill_ref:
                    raise ValueError("api.publisher_result_invalid")
                hosted.saved_ref = skill_ref
                hosted.state = SessionState.SAVED
                return {
                    "state": hosted.state.value,
                    "skill_ref": skill_ref,
                    "artifact_hash": hosted.artifact_hash,
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    return router


rpa_agent_default_services = RpaAgentApiServices(
    artifact_root=Path(
        os.environ.get(
            "RPA_AGENT_ARTIFACT_ROOT",
            str(Path(__file__).resolve().parents[1] / ".rpa-agent-artifacts"),
        )
    ),
    browser_provider=_scienceclaw_browser_provider,
    agent_executor=execute_browser_use_instruction,
    runtime_runner=run_compiled_skill_with_agent,
    publisher=lambda hosted: publish_compiled_skill(
        hosted,
        destination_root=Path(settings.external_skills_dir),
    ),
)
router = build_router(rpa_agent_default_services)


__all__ = [
    "RpaAgentApiServices",
    "build_router",
    "router",
    "rpa_agent_default_services",
]
