"""Isolated public API for RPA Agent Next.

This module deliberately has no import from ``route.rpa_agent`` or the legacy
RPA session, trace, compiler, or asset modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.rpa_agent.application import (
    NextRecordingHostFactory,
    RpaAgentNextSessionOrchestrator,
    SessionNotFoundError,
    SessionOwnerError,
)
from backend.config import settings
from backend.rpa_agent.contracts import (
    ArtifactIngressError,
    ArtifactKind,
    ArtifactProducer,
    require_next_identity,
)
from backend.rpa_agent.host import BrowserHostSession
from backend.rpa_agent.host.native_browser_use_runner import NativeBrowserUseRunner
from backend.rpa_agent.platform import (
    DockerBrowserHostFactory,
    FilePolicy,
    RuntimeHealth,
    RuntimeLease,
    RuntimeLeaseError,
    RuntimeProviderPort,
)
from backend.rpa_agent.host.scienceclaw_browser import acquire_browser_runtime_lease
from backend.runtime.docker_runtime_provider import DockerRuntimeProvider as GenericDockerRuntimeProvider
from backend.runtime.rpa_agent_next_docker_provider import DockerRuntimeProvider
from backend.runtime.session_runtime_manager import SessionRuntimeManager
from backend.rpa_agent.recording.ai_execution import (
    BrowserUseExecutionPort,
    BrowserUseExecutionRequest,
)
from backend.user.dependencies import User, require_user


class _NextBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    identity: dict[str, object]


class _StartSessionBody(_NextBody):
    pass


class _InstructionBody(_NextBody):
    instruction: str = Field(min_length=1, max_length=20_000)
    model_ref: str = Field(default="runtime_default", min_length=1, max_length=256)


class _UnavailableRuntimeProvider:
    async def acquire(
        self, session_id: str, user_id: str, purpose: str
    ) -> RuntimeLease:
        del session_id, user_id, purpose
        raise RuntimeLeaseError("rpa_agent_next.runtime_unavailable")

    async def release(self, lease: RuntimeLease, reason: str) -> None:
        del lease, reason

    async def health(self, lease: RuntimeLease) -> RuntimeHealth:
        del lease
        return RuntimeHealth(state="released")

    async def resolve_file_policy(self, lease: RuntimeLease) -> FilePolicy:
        del lease
        raise RuntimeLeaseError("rpa_agent_next.runtime_unavailable")


class _UnavailableHostFactory:
    async def create_recording(
        self, *, owner_id: str, lease: RuntimeLease
    ) -> BrowserHostSession:
        del owner_id, lease
        raise RuntimeError("rpa_agent_next.browser_host_unavailable")


class _UnavailableRunner:
    async def execute(self, request: BrowserUseExecutionRequest) -> object:
        del request
        raise RuntimeError("rpa_agent_next.browser_use_unavailable")


@dataclass(slots=True)
class RpaAgentNextApiServices:
    runtime_provider: RuntimeProviderPort | None = None
    host_factory: NextRecordingHostFactory | None = None
    runner_factory: Any | None = None
    orchestrator: RpaAgentNextSessionOrchestrator | None = None

    def __post_init__(self) -> None:
        if self.orchestrator is not None:
            return
        runtime_provider = self.runtime_provider or _UnavailableRuntimeProvider()
        host_factory = self.host_factory or _UnavailableHostFactory()
        runner_factory = self.runner_factory or (lambda _owner_id: _UnavailableRunner())
        self.orchestrator = RpaAgentNextSessionOrchestrator(
            runtime_provider=runtime_provider,
            host_factory=host_factory,
            runner_factory=runner_factory,
        )


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


def _owner(user: User) -> str:
    if not user.id:
        raise _error(status.HTTP_401_UNAUTHORIZED, "rpa_agent_next.unauthenticated")
    return user.id


async def _read_next_body(
    request: Request,
    model: type[_StartSessionBody] | type[_InstructionBody],
    *,
    session_id: str | None = None,
):
    try:
        raw = await request.json()
    except Exception as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "rpa_agent_next.request_invalid") from error
    if not isinstance(raw, Mapping):
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "rpa_agent_next.request_invalid")
    envelope = raw.get("identity")
    if not isinstance(envelope, Mapping):
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "rpa_agent_next.legacy_or_unknown_artifact")
    try:
        identity = require_next_identity(
            envelope,
            entrypoint="rpa_agent_next.api",
            allowed_kinds=(ArtifactKind.RECORDING_TIMELINE,),
        )
    except ArtifactIngressError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code) from error
    if identity.producer is not ArtifactProducer.RPA_CORE:
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "rpa_agent_next.identity_producer_invalid")
    if session_id is not None and identity.artifact_id != session_id:
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "rpa_agent_next.identity_session_mismatch")
    try:
        body = model.model_validate(raw)
    except ValidationError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "rpa_agent_next.request_invalid") from error
    return identity, body


def build_router(services: RpaAgentNextApiServices) -> APIRouter:
    router = APIRouter()
    assert services.orchestrator is not None

    @router.post("/sessions", status_code=status.HTTP_201_CREATED)
    async def start_session(request: Request, user: User = Depends(require_user)):
        identity, _body = await _read_next_body(request, _StartSessionBody)
        try:
            recording = await services.orchestrator.start(
                session_id=identity.artifact_id,
                owner_id=_owner(user),
            )
        except RuntimeLeaseError as error:
            raise _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "rpa_agent_next.runtime_unavailable",
            ) from error
        except RuntimeError as error:
            raise _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "rpa_agent_next.browser_host_unavailable",
            ) from error
        except SessionOwnerError as error:
            raise _error(status.HTTP_404_NOT_FOUND, error.code) from error
        return {
            "session_id": identity.artifact_id,
            "schema_namespace": "rpa-agent-next/v1",
            "items": [
                item.model_dump(mode="json", exclude_none=True)
                for item in recording.projection_items()
            ],
        }

    @router.get("/sessions/{session_id}/projection")
    async def projection(session_id: str, user: User = Depends(require_user)):
        try:
            return await services.orchestrator.projection(
                session_id=session_id,
                owner_id=_owner(user),
            )
        except SessionNotFoundError as error:
            raise _error(status.HTTP_404_NOT_FOUND, error.code) from error
        except SessionOwnerError as error:
            raise _error(status.HTTP_404_NOT_FOUND, error.code) from error

    @router.post("/sessions/{session_id}/instructions", status_code=status.HTTP_201_CREATED)
    async def execute_instruction(
        session_id: str,
        request: Request,
        user: User = Depends(require_user),
    ):
        _identity, body = await _read_next_body(
            request, _InstructionBody, session_id=session_id
        )
        try:
            return await services.orchestrator.execute_instruction(
                session_id=session_id,
                owner_id=_owner(user),
                instruction=body.instruction,
                model_ref=body.model_ref,
            )
        except SessionNotFoundError as error:
            raise _error(status.HTTP_404_NOT_FOUND, error.code) from error
        except SessionOwnerError as error:
            raise _error(status.HTTP_404_NOT_FOUND, error.code) from error

    @router.delete("/sessions/{session_id}")
    async def close_session(session_id: str, user: User = Depends(require_user)):
        try:
            closed = await services.orchestrator.close(
                session_id=session_id,
                owner_id=_owner(user),
            )
        except SessionOwnerError as error:
            raise _error(status.HTTP_404_NOT_FOUND, error.code) from error
        except RuntimeLeaseError as error:
            raise _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "rpa_agent_next.runtime_release_failed",
            ) from error
        return {"session_id": session_id, "closed": closed}

    return router


def build_default_services(
    *,
    next_settings: object = settings,
    runtime_manager: object | None = None,
    preview_registry: object | None = None,
) -> RpaAgentNextApiServices:
    """Build the only opt-in edge composition for RPA Agent Next.

    Disabled is intentionally the default.  It avoids silently changing the
    existing API from fail-closed to an in-process fake runtime.
    """

    if getattr(next_settings, "rpa_agent_next_runtime_mode", "disabled") != "docker":
        return RpaAgentNextApiServices()
    if runtime_manager is None:
        runtime_manager = SessionRuntimeManager(
            provider=GenericDockerRuntimeProvider(next_settings),
            settings=next_settings,
        )
    if preview_registry is None:
        from backend.browser_preview import browser_preview_registry

        preview_registry = browser_preview_registry
    runtime_provider = DockerRuntimeProvider(runtime_manager)
    host_factory = DockerBrowserHostFactory(
        resolve_cdp_url=runtime_provider.resolve_cdp_url,
        preview_registry=preview_registry,
        acquire_runtime_lease=acquire_browser_runtime_lease,
    )
    return RpaAgentNextApiServices(
        runtime_provider=runtime_provider,
        host_factory=host_factory,
        runner_factory=lambda owner_id: NativeBrowserUseRunner(owner_id=owner_id),
    )


rpa_agent_next_default_services = build_default_services()
router = build_router(rpa_agent_next_default_services)


__all__ = [
    "RpaAgentNextApiServices",
    "build_default_services",
    "build_router",
    "router",
    "rpa_agent_next_default_services",
]
