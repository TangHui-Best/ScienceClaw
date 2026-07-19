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
import secrets
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from backend.config import settings
from backend.rpa_agent.api.models import (
    AgentInstructionAcceptedResponse,
    AgentInstructionRequest,
    ManualEventRequest,
    ManualInputRequest,
    ManualReservationRequest,
    StartSessionRequest,
    StartSessionResponse,
    TestRunRequest,
)
from backend.rpa_agent.browser_use import RecordingRoundReport
from backend.rpa_agent.compiler import (
    DeterministicCompiler,
    assess_recording_timeline,
    compile_dual_mode_plan,
    materialize_core_trace_timeline,
)
from backend.rpa_agent.contracts import (
    AgentStepConfiguration,
    CompilationConfiguration,
    PageSummary,
    RuntimeModelPolicy,
)
from backend.rpa_agent.configuration import (
    ConfigurationError,
    SkillConfigurationDraft,
    transform_configuration,
)
from backend.rpa_agent.creation import (
    ControlMode,
    SkillCreationSession,
    project_recording_items,
)
from backend.rpa_agent.host import (
    AgentIdempotencyRecord,
    BrowserHostSession,
    BrowserRunSessionFactory,
    BrowserSession,
    BrowserSessionPort,
    HostedSession,
    ManualIdempotencyRecord,
    SessionState,
    SessionStore,
    ManualInputCommand,
    publish_compiled_skill,
    new_host_identity,
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
    [HostedSession, AgentInstructionRequest], Awaitable[object]
]
RuntimeRunner = Callable[[HostedSession, TestRunRequest], Awaitable[Mapping[str, Any]]]
Publisher = Callable[[HostedSession], Awaitable[Mapping[str, str]]]


class _ProviderRunSessionFactory:
    """Compatibility adapter for injected tests; production uses an owned factory."""

    def __init__(self, provider: BrowserProvider) -> None:
        self._provider = provider

    async def _create(self, owner_id: str, prefix: str) -> BrowserHostSession:
        browser_ref, generation = new_host_identity(prefix)
        port = await self._provider(owner_id, browser_ref)
        return BrowserHostSession(
            browser_session_ref=browser_ref,
            page_ref=port.main_page_runtime_ref,
            target_id=port.main_page_runtime_ref,
            generation=generation,
            port=port,
        )

    async def create_recording(self, *, owner_id: str) -> BrowserHostSession:
        return await self._create(owner_id, "bhs_recording")

    async def create_test(self, *, owner_id: str, skill_id: str) -> BrowserHostSession:
        del skill_id
        return await self._create(owner_id, "bhs_test")

    async def create_run(self, *, owner_id: str, skill_id: str) -> BrowserHostSession:
        del skill_id
        return await self._create(owner_id, "bhs_run")


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

    factory_owned_local_ref = (
        settings.storage_backend.strip().lower() == "local"
        and browser_ref.startswith(("bhs_recording_", "bhs_test_", "bhs_run_"))
    )
    if not factory_owned_local_ref and not await user_owns_runtime_session(browser_ref, owner_id):
        raise RuntimeError("browser_host_not_owned")
    from backend.rpa_agent.host.scienceclaw_browser import (
        acquire_browser_runtime_lease,
    )

    runtime_lease = await acquire_browser_runtime_lease(
        owner_id=owner_id,
        browser_ref=browser_ref,
        preview_registry=browser_preview_registry,
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
    browser_factory: BrowserRunSessionFactory | None = None
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
        if self.browser_factory is None:
            self.browser_factory = _ProviderRunSessionFactory(self.browser_provider)
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


def _error(
    status_code: int, code: str, *, details: list[dict[str, object]] | None = None
) -> HTTPException:
    detail: dict[str, object] = {"code": code}
    if details:
        detail["details"] = details
    return HTTPException(status_code=status_code, detail=detail)


def _owner(user: User) -> str:
    if not user.id:
        raise _error(401, "rpa_agent.unauthenticated")
    return user.id


def _require_new_session_id(session_id: str) -> None:
    if _SESSION_ID.fullmatch(session_id) is None:
        raise _error(404, "rpa_agent.session_not_found")


def _state_error(exc: ValueError) -> HTTPException:
    code = str(exc).split(":", 1)[0]
    logger.warning("rpa_agent operation rejected error_code=%s", code)
    if code == "api.state_conflict":
        return _error(409, "rpa_agent.state_conflict")
    if code == "api.artifact_changed":
        return _error(409, "rpa_agent.artifact_changed")
    if code.startswith("manual_reservation"):
        return _error(409, f"rpa_agent.{code}")
    if code.startswith("browser_session.pending_fact"):
        return _error(409, "rpa_agent.pending_browser_fact")
    if code == "recording_timeline.drafts_incomplete":
        draft_ids = str(exc).split(":", 1)[1].split(",")
        return HTTPException(
            status_code=409,
            detail={
                "code": "rpa_agent.recording_drafts_incomplete",
                "draft_ids": draft_ids,
            },
        )
    if code in {
        "agent_instruction_in_progress",
        "session_operation_in_progress",
        "idempotency_conflict",
        "manual_input_idempotency_conflict",
    }:
        return _error(409, f"rpa_agent.{code}")
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
    }


def build_router(services: RpaAgentApiServices) -> APIRouter:
    router = APIRouter(tags=["RPA Agent"], route_class=_SafeValidationRoute)
    assert services.store is not None
    assert services.compiler is not None

    async def run_agent_task(
        hosted: HostedSession,
        *,
        step_id: str,
        body: AgentInstructionRequest,
    ) -> None:
        try:
            async with hosted.lock:
                hosted.browser.creation.mark_ai_instruction_running(
                    step_id, started_at=datetime.now(timezone.utc)
                )
            returned = await services.agent_executor(hosted, body)  # type: ignore[misc]
            summary = "Browser-use completed."
            if isinstance(returned, RecordingRoundReport):
                summary = (
                    "Browser-use completed with "
                    f"{returned.actual_action_count} observed actions."
                )
            async with hosted.lock:
                hosted.browser.creation.finish_ai_instruction(
                    step_id,
                    finished_at=datetime.now(timezone.utc),
                    succeeded=True,
                    result_summary=summary,
                )
        except asyncio.CancelledError:
            async with hosted.lock:
                try:
                    hosted.browser.creation.cancel_ai_instruction(
                        step_id, finished_at=datetime.now(timezone.utc)
                    )
                except ValueError:
                    pass
            raise
        except BaseException as exc:
            logger.warning(
                "rpa_agent async instruction failed step_id=%s error_type=%s",
                step_id,
                type(exc).__name__,
            )
            async with hosted.lock:
                try:
                    hosted.browser.creation.finish_ai_instruction(
                        step_id,
                        finished_at=datetime.now(timezone.utc),
                        succeeded=False,
                        error_code="agent_execution_failed",
                        error_message="Browser-use execution failed.",
                    )
                except ValueError:
                    pass
        finally:
            async with hosted.lock:
                try:
                    hosted.browser.creation.switch_control(
                        ControlMode.HUMAN, at=datetime.now(timezone.utc)
                    )
                except ValueError:
                    pass
                if hosted.active_operation_id == step_id:
                    hosted.release_operation(operation_id=step_id)
                hosted.agent_tasks.pop(step_id, None)
                hosted.touch()

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
            assert services.browser_factory is not None
            browser_host = await services.browser_factory.create_recording(
                owner_id=owner_id
            )
            port = browser_host.port
            if body.start_url is not None:
                goto = getattr(port.main_page, "goto", None)
                if not callable(goto):
                    raise RuntimeError("browser_host_navigation_unavailable")
                await goto(body.start_url)
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
                browser_session_ref=browser_host.browser_session_ref,
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
                "browser_session_ref": browser_host.browser_session_ref,
                "page_ref": browser_host.page_ref,
                "generation": browser_host.generation,
            }
        )

    @router.post(
        "/sessions/{session_id}/rerecord",
        status_code=status.HTTP_201_CREATED,
        response_model=StartSessionResponse,
    )
    async def rerecord_session(
        session_id: str,
        body: StartSessionRequest,
        user: User = Depends(require_user),
    ):
        _require_new_session_id(session_id)
        owner_id = _owner(user)
        try:
            retired = await services.store.pop(session_id, owner_id=owner_id)
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        tasks = tuple(retired.agent_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            if retired.test_browser_host is not None:
                await retired.test_browser_host.aclose()
                retired.test_browser_host = None
            await retired.browser.aclose(at=datetime.now(timezone.utc))
        except BaseException as exc:
            logger.warning(
                "rpa_agent rerecord cleanup failed error_type=%s", type(exc).__name__
            )
            raise _error(503, "rpa_agent.rerecord_cleanup_failed") from None

        try:
            assert services.browser_factory is not None
            browser_host = await services.browser_factory.create_recording(
                owner_id=owner_id
            )
            port = browser_host.port
            if body.start_url is not None:
                goto = getattr(port.main_page, "goto", None)
                if not callable(goto):
                    raise RuntimeError("browser_host_navigation_unavailable")
                await goto(body.start_url)
            creation = SkillCreationSession(
                session_id="creation_" + hashlib.sha256(os.urandom(32)).hexdigest()[:16],
                main_runtime_ref=port.main_page_runtime_ref,
                fact_buffer_capacity=256,
                fact_ttl=timedelta(seconds=30),
            )
            browser = BrowserSession(port=port, creation=creation)
            browser.attach()
            hosted = await services.store.create(
                owner_id=owner_id,
                browser_session_ref=browser_host.browser_session_ref,
                browser=browser,
                artifact_dir=services.artifact_root,
            )
        except BaseException as exc:
            logger.warning(
                "rpa_agent rerecord create failed error_type=%s", type(exc).__name__
            )
            raise _error(503, "rpa_agent.browser_host_unavailable") from None
        return StartSessionResponse(
            session_id=hosted.session_id,
            state="recording",
            browser_session_ref=browser_host.browser_session_ref,
            page_ref=browser_host.page_ref,
            generation=browser_host.generation,
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
        owner_id = _owner(user)
        request_hash = hashlib.sha256(
            json.dumps(
                body.model_dump(mode="json", exclude_none=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        draft_id = "draft_" + secrets.token_hex(12)
        try:
            async with services.store.use(session_id, owner_id=owner_id) as hosted:
                hosted.require_state(SessionState.RECORDING)
                existing = hosted.manual_idempotency.get(body.input_id)
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise ValueError("manual_input_idempotency_conflict")
                    return {
                        "input_id": body.input_id,
                        "draft_id": existing.draft_id,
                        "capture_status": existing.capture_status,
                    }
                hosted.reserve_operation(operation_id=draft_id, kind="manual")
                _, draft_ordinal = hosted.browser.creation.begin_manual_draft(
                    draft_id=draft_id
                )
                hosted.manual_idempotency[body.input_id] = ManualIdempotencyRecord(
                    request_hash=request_hash,
                    draft_id=draft_id,
                    capture_status="capturing",
                )

            try:
                if body.kind == "navigate":
                    assert body.text is not None
                    goto = getattr(hosted.browser.main_page, "goto", None)
                    if not callable(goto):
                        raise RuntimeError("manual_input.navigation_unavailable")
                    await goto(body.text)
                    trace = hosted.browser.creation.complete_manual_navigation(
                        draft_id=draft_id,
                        trace_id="trace_" + secrets.token_hex(12),
                        ordinal=draft_ordinal,
                        page_ref=hosted.browser.creation.pages.resolve(
                            hosted.browser.port.main_page_runtime_ref
                        ),
                        url=body.text,
                    )
                    result = SimpleNamespace(
                        input_id=body.input_id,
                        candidate_id=draft_id,
                        candidate_ids=(trace.trace_id,),
                    )
                else:
                    result = await hosted.browser.dispatch_manual_input(
                        ManualInputCommand(
                            input_id=body.input_id,
                            kind=body.kind,
                            draft_id=draft_id,
                            x=body.x,
                            y=body.y,
                            text=body.text,
                        )
                    )
            except BaseException:
                async with services.store.use(session_id, owner_id=owner_id) as current:
                    current.browser.creation.fail_manual_draft(
                        draft_id=draft_id,
                        diagnostic_code="manual_input.dispatch_failed",
                    )
                    record = current.manual_idempotency[body.input_id]
                    record.capture_status = "incomplete"
                    if current.active_operation_id == draft_id:
                        current.release_operation(operation_id=draft_id)
                raise

            async with services.store.use(session_id, owner_id=owner_id) as current:
                effective_draft_id = result.candidate_id
                if effective_draft_id != draft_id:
                    current.browser.creation.discard_manual_draft(draft_id=draft_id)
                items = current.browser.creation.recording_projection_items()
                finalized = any(
                    getattr(item, "trace_id", None) is not None
                    and getattr(item, "sequence", None) is not None
                    and effective_draft_id not in {
                        getattr(item, "draft_id", None),
                        getattr(item, "step_id", None),
                    }
                    for item in items
                ) and bool(result.candidate_ids)
                capture_status = "captured" if finalized else "capturing"
                record = current.manual_idempotency[body.input_id]
                record.draft_id = effective_draft_id
                record.capture_status = capture_status
                current.release_operation(operation_id=draft_id)
                return {
                    "input_id": result.input_id,
                    "draft_id": effective_draft_id,
                    "capture_status": capture_status,
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except RuntimeError:
            raise _error(503, "rpa_agent.manual_input_unavailable") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.delete("/sessions/{session_id}/manual-inputs/{input_id}")
    async def discard_manual_input(
        session_id: str, input_id: str, user: User = Depends(require_user)
    ):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.RECORDING)
                record = hosted.manual_idempotency.get(input_id)
                if record is None:
                    raise KeyError("manual_input.not_found")
                if record.capture_status != "incomplete":
                    raise ValueError("manual_input_not_discardable")
                hosted.browser.creation.discard_manual_draft(draft_id=record.draft_id)
                del hosted.manual_idempotency[input_id]
                return {"input_id": input_id, "state": "discarded"}
        except KeyError:
            raise _error(404, "rpa_agent.manual_input_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.post(
        "/sessions/{session_id}/agent-instructions",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AgentInstructionAcceptedResponse,
    )
    async def agent_instruction(
        session_id: str,
        body: AgentInstructionRequest,
        user: User = Depends(require_user),
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=16, max_length=128
        ),
    ):
        _require_new_session_id(session_id)
        if services.agent_executor is None:
            raise _error(503, "rpa_agent.agent_unavailable")
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                hosted.require_state(SessionState.RECORDING)
                request_hash = hashlib.sha256(
                    json.dumps(
                        body.model_dump(mode="json", exclude_none=True),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                existing = hosted.agent_idempotency.get(idempotency_key)
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise ValueError("idempotency_conflict")
                    timeline = hosted.browser.creation.recording_timeline()
                    ordinal, existing_step = next(
                        (index, item)
                        for index, item in enumerate(timeline.items, start=1)
                        if getattr(item, "step_id", None) == existing.step_id
                    )
                    return AgentInstructionAcceptedResponse(
                        step_id=existing.step_id,
                        ordinal=ordinal,
                        execution_status=existing_step.execution.status,
                    )
                step_id = "ais_" + secrets.token_hex(12)
                hosted.reserve_operation(operation_id=step_id, kind="agent")
                now = datetime.now(timezone.utc)
                hosted.browser.enter_agent_control(at=now)
                _, ordinal = hosted.browser.creation.queue_ai_instruction(
                    step_id=step_id,
                    instruction=body.instruction,
                    model_ref=body.model_id or "runtime_default",
                    context_snapshot_ref="ctx_" + secrets.token_hex(12),
                    created_at=now,
                    declared_outputs=tuple(body.declared_outputs),
                    expected_effects=tuple(body.expected_effects),
                )
                hosted.agent_idempotency[idempotency_key] = AgentIdempotencyRecord(
                    request_hash=request_hash,
                    step_id=step_id,
                )
                hosted.agent_step_configurations[step_id] = AgentStepConfiguration(
                    step_id=step_id,
                    output_refs=[output.name for output in body.declared_outputs],
                    expected_effects=list(body.expected_effects),
                    allowed_input_refs=list(body.allowed_inputs),
                    allowed_secret_refs=list(body.allowed_secret_names),
                    allowed_asset_refs=list(body.allowed_data_assets),
                    page_aliases={
                        ref: PageSummary(page_ref=ref, url="", title=title)
                        for ref, title in body.page_aliases.items()
                    },
                    business_terms=list(body.business_terms),
                    model_policy=RuntimeModelPolicy(
                        mode="configured_model" if body.model_id else "runtime_default",
                        model_ref=body.model_id,
                    ),
                    timeout_seconds=180,
                )
                task = asyncio.create_task(
                    run_agent_task(hosted, step_id=step_id, body=body),
                    name=f"rpa-agent:{session_id}:{step_id}",
                )
                hosted.agent_tasks[step_id] = task
                return AgentInstructionAcceptedResponse(
                    step_id=step_id,
                    ordinal=ordinal,
                    execution_status="queued",
                )
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None

    @router.get("/sessions/{session_id}/projection")
    async def projection(session_id: str, user: User = Depends(require_user)):
        _require_new_session_id(session_id)
        try:
            async with services.store.use(session_id, owner_id=_owner(user)) as hosted:
                live_items, observed_traces = (
                    hosted.browser.creation.recording_projection_state()
                )
                items = project_recording_items(
                    live_items, observed_traces, hosted.replay_assessments
                )
                return {
                    "session_id": hosted.session_id,
                    "recording_state": hosted.state.value,
                    "items": [
                        {
                            **asdict(item),
                            "observations": [asdict(observation) for observation in item.observations],
                        }
                        for item in items
                    ],
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None

    @router.post("/sessions/{session_id}/stop")
    async def stop_session(session_id: str, user: User = Depends(require_user)):
        _require_new_session_id(session_id)
        owner_id = _owner(user)
        tasks: tuple[asyncio.Task[None], ...] = ()
        try:
            async with services.store.use(session_id, owner_id=owner_id) as hosted:
                hosted.require_state(SessionState.RECORDING)
                if hosted.admission_closed:
                    raise ValueError("session_admission_closed")
                if (
                    hosted.active_operation_id is not None
                    and hosted.active_operation_kind != "agent"
                ):
                    raise ValueError("session_operation_in_progress")
                hosted.admission_closed = True
                tasks = tuple(hosted.agent_tasks.values())

            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            async with services.store.use(session_id, owner_id=owner_id) as hosted:
                hosted.require_state(SessionState.RECORDING)
                now = datetime.now(timezone.utc)
                await hosted.browser.drain_pending_facts(timeout=30)
                hosted.browser.finalize_recording(at=now)
                hosted.recording_timeline = hosted.browser.creation.recording_timeline()
                hosted.replay_assessments = assess_recording_timeline(
                    hosted.recording_timeline
                )
                hosted.browser.detach()
                hosted.configuration_draft = _draft(hosted.browser.creation)
                hosted.configuration_draft = SkillConfigurationDraft.model_validate(
                    {
                        **hosted.configuration_draft.model_dump(mode="json"),
                        "agent_steps": {
                            key: value.model_dump(mode="json")
                            for key, value in hosted.agent_step_configurations.items()
                        },
                        "manual_fallbacks": {},
                    }
                )
                hosted.state = SessionState.STOPPED
                hosted.admission_closed = False
                return {
                    "state": hosted.state.value,
                    "configuration_draft": hosted.configuration_draft.model_dump(
                        mode="json", exclude_unset=True
                    ),
                    "configuration_options": _configuration_options(
                        hosted.browser.creation, hosted.configuration_draft
                    ),
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            try:
                async with services.store.use(session_id, owner_id=owner_id) as hosted:
                    if hosted.state is SessionState.RECORDING:
                        hosted.admission_closed = False
            except KeyError:
                pass
            raise _state_error(exc) from None
        except BaseException:
            try:
                async with services.store.use(session_id, owner_id=owner_id) as hosted:
                    if hosted.state is SessionState.RECORDING:
                        hosted.admission_closed = False
            except KeyError:
                pass
            raise

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
                configured_agent_steps = (
                    dict(body.agent_steps)
                    if "agent_steps" in body.model_fields_set
                    else dict(hosted.agent_step_configurations)
                )
                configured_fallbacks = (
                    dict(body.manual_fallbacks)
                    if "manual_fallbacks" in body.model_fields_set
                    else dict(hosted.manual_fallbacks)
                )
                compilation_configuration = CompilationConfiguration(
                    skill_definition=hosted.configuration.skill_definition,
                    manual_fallbacks=configured_fallbacks,
                    agent_steps=configured_agent_steps,
                )
                hosted.manual_fallbacks = dict(compilation_configuration.manual_fallbacks)
                hosted.agent_step_configurations = dict(compilation_configuration.agent_steps)
                hosted.state = SessionState.CONFIGURED
                await hosted.browser.aclose(at=datetime.now(timezone.utc))
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
                if hosted.recording_timeline is None:
                    raise ValueError("api.recording_timeline_missing")
                compilation_configuration = CompilationConfiguration(
                    skill_definition=hosted.configuration.skill_definition,
                    manual_fallbacks=dict(hosted.manual_fallbacks),
                    agent_steps=dict(hosted.agent_step_configurations),
                )
                hosted.compiled_plan = compile_dual_mode_plan(
                    hosted.recording_timeline,
                    hosted.replay_assessments,
                    compilation_configuration,
                )
                renderer_timeline = materialize_core_trace_timeline(
                    hosted.compiled_plan, compilation_configuration
                )
                result = services.compiler.compile(
                    renderer_timeline,
                    hosted.configuration.skill_definition,
                    hosted.artifact_dir,
                    source_hash=hosted.compiled_plan.source_hash,
                    source_item_count=len(hosted.compiled_plan.steps),
                    compiled_plan=hosted.compiled_plan,
                    agent_policies=dict(hosted.agent_step_configurations),
                )
                if result.status != "published" or result.artifacts is None:
                    raise _error(
                        422,
                        "rpa_agent.compile_rejected",
                        details=[asdict(issue) for issue in result.issues],
                    )
                if set(result.artifacts.files) != _REQUIRED_ARTIFACT_FILES:
                    raise _error(422, "rpa_agent.compile_rejected")
                hosted.compile_result = result
                hosted.artifact_hash = _artifact_hash_from_disk(hosted.artifact_dir)
                hosted.state = SessionState.COMPILED
                return {
                    "state": hosted.state.value,
                    "artifact_files": sorted(result.artifacts.files),
                    "artifact_hash": hosted.artifact_hash,
                    "source_hash": hosted.compiled_plan.source_hash,
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
        owner_id = _owner(user)
        operation_id = "test_" + secrets.token_hex(12)
        test_host: BrowserHostSession | None = None
        previous_test_host: BrowserHostSession | None = None
        try:
            async with services.store.use(session_id, owner_id=owner_id) as hosted:
                hosted.require_state(SessionState.COMPILED, SessionState.TESTED)
                if hosted.compile_result is None or hosted.artifact_hash is None:
                    raise ValueError("api.compiled_artifact_missing")
                _require_artifact_unchanged(hosted)
                hosted.reserve_operation(operation_id=operation_id, kind="test")
                previous_test_host = hosted.test_browser_host
                hosted.test_browser_host = None
                skill_id = hosted.configuration.skill_definition.skill.id  # type: ignore[union-attr]
                run_view = SimpleNamespace(
                    owner_id=hosted.owner_id,
                    configuration=hosted.configuration,
                    artifact_dir=hosted.artifact_dir,
                )

            if previous_test_host is not None:
                await previous_test_host.aclose()
            assert services.browser_factory is not None
            test_host = await services.browser_factory.create_test(
                owner_id=owner_id, skill_id=skill_id
            )
            run_view.browser = SimpleNamespace(
                main_page=test_host.port.main_page,
                port=test_host.port,
            )
            raw = await services.runtime_runner(run_view, body)
            if not isinstance(raw, Mapping):
                raise ValueError("api.run_result_invalid")
            secret_values = frozenset(body.secrets.values())
            result = _sanitize(dict(raw), secret_values=secret_values)

            async with services.store.use(session_id, owner_id=owner_id) as hosted:
                _require_artifact_unchanged(hosted)
                hosted.run_result = result
                hosted.test_passed = result.get("status") == "succeeded"
                if hosted.test_passed:
                    hosted.state = SessionState.TESTED
                hosted.test_browser_host = test_host
                test_host = None
                hosted.release_operation(operation_id=operation_id)
                return {
                    "state": hosted.state.value,
                    "artifact_hash": hosted.artifact_hash,
                    "run_result": result,
                    "test_session": {
                        "browser_session_ref": hosted.test_browser_host.browser_session_ref,
                        "page_ref": hosted.test_browser_host.page_ref,
                        "target_id": hosted.test_browser_host.target_id,
                        "generation": hosted.test_browser_host.generation,
                    },
                    "compiled_steps": [
                        {
                            "step_id": step.step_id,
                            "ordinal": step.ordinal,
                            "mode": step.mode,
                            "output_refs": (
                                list(step.output_refs)
                                if step.mode == "agent"
                                else [output.name for output in step.expected_outputs]
                            ),
                            "expected_effects": [
                                effect.model_dump(mode="json", exclude_none=True)
                                for effect in step.expected_effects
                            ],
                        }
                        for step in (hosted.compiled_plan.steps if hosted.compiled_plan else [])
                    ],
                }
        except KeyError:
            raise _error(404, "rpa_agent.session_not_found") from None
        except ValueError as exc:
            raise _state_error(exc) from None
        finally:
            if test_host is not None:
                await test_host.aclose()
            try:
                async with services.store.use(session_id, owner_id=owner_id) as hosted:
                    if hosted.active_operation_id == operation_id:
                        hosted.release_operation(operation_id=operation_id)
            except KeyError:
                pass

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
                if hosted.test_browser_host is not None:
                    await hosted.test_browser_host.aclose()
                    hosted.test_browser_host = None
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
