from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rpa_agent.host import BrowserHostSession
from rpa_agent.platform import FakeRuntimeProvider, RuntimeLease
from rpa_agent.recording.ai_execution import BrowserUseExecutionResult
from backend.route.rpa_agent_next import RpaAgentNextApiServices, build_router
from backend.user.dependencies import User, require_user


class _Port:
    main_page_runtime_ref = "page_1"
    browser_use_cdp_url = "http://cdp.example.test"

    def __init__(self) -> None:
        self._callbacks: dict[str, list[Callable[[object], None]]] = defaultdict(list)
        self.released: list[str] = []
        self.closed = 0
        self.page = object()

    def subscribe(self, kind: str, callback: Callable[[object], None]):
        self._callbacks[kind].append(callback)

        def release() -> None:
            self.released.append(kind)
            self._callbacks[kind].remove(callback)

        return release

    async def active_page_object(self) -> object:
        return self.page

    async def aclose(self) -> None:
        self.closed += 1


class _HostFactory:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.port = _Port()
        self.leases: list[RuntimeLease] = []

    async def create_recording(self, *, owner_id: str, lease: RuntimeLease):
        assert owner_id == "user-1"
        self.leases.append(lease)
        if self.fail:
            raise RuntimeError("host setup failed")
        return BrowserHostSession(
            browser_session_ref="host_1",
            page_ref="page_1",
            target_id="target_1",
            generation="generation_1",
            port=self.port,
        )


class _Runner:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return BrowserUseExecutionResult(result_summary="completed")


def _identity(session_id: str, *, namespace: str = "rpa-agent-next/v1") -> dict[str, str]:
    return {
        "schema_namespace": namespace,
        "artifact_kind": "recording_timeline",
        "artifact_id": session_id,
        "producer": "rpa-core",
    }


def _client(*, runtime=None, host_factory=None, runner=None) -> TestClient:
    services = RpaAgentNextApiServices(
        runtime_provider=runtime or FakeRuntimeProvider(),
        host_factory=host_factory or _HostFactory(),
        runner_factory=lambda _owner_id: runner or _Runner(),
    )
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/rpa-agent-next")
    app.dependency_overrides[require_user] = lambda: User(
        id="user-1", username="tester", role="user"
    )
    return TestClient(app)


def test_next_api_composes_runtime_host_timeline_and_reverse_cleanup() -> None:
    runtime = FakeRuntimeProvider()
    host_factory = _HostFactory()
    runner = _Runner()
    client = _client(runtime=runtime, host_factory=host_factory, runner=runner)
    session_id = "next_session_1"

    start = client.post("/api/rpa-agent-next/sessions", json={"identity": _identity(session_id)})
    assert start.status_code == 201, start.text
    assert start.json() == {
        "session_id": session_id,
        "schema_namespace": "rpa-agent-next/v1",
        "items": [],
    }
    assert host_factory.leases[0].session_id == session_id

    instruction = client.post(
        f"/api/rpa-agent-next/sessions/{session_id}/instructions",
        json={
            "identity": _identity(session_id),
            "instruction": "open the purchase order",
            "model_ref": "model_1",
        },
    )
    assert instruction.status_code == 201, instruction.text
    assert instruction.json()["execution"]["status"] == "succeeded"
    assert runner.requests[0].cdp_url == "http://cdp.example.test"
    assert runner.requests[0].page is host_factory.port.page

    projection = client.get(f"/api/rpa-agent-next/sessions/{session_id}/projection")
    assert projection.status_code == 200, projection.text
    assert [item["step_id"] for item in projection.json()["timeline"]["items"]] == [
        instruction.json()["step_id"]
    ]
    assert "expected_effects" not in projection.text

    closed = client.delete(f"/api/rpa-agent-next/sessions/{session_id}")
    assert closed.status_code == 200
    assert closed.json()["closed"] is True
    assert host_factory.port.released == ["download", "new_page", "navigation"]
    assert host_factory.port.closed == 1
    assert runtime.release_reasons == [
        (f"lease:{session_id}", "rpa_agent_next.session_closed")
    ]
    assert client.delete(f"/api/rpa-agent-next/sessions/{session_id}").json()["closed"] is False


def test_start_failure_releases_lease_without_registering_a_next_session() -> None:
    runtime = FakeRuntimeProvider()
    client = _client(runtime=runtime, host_factory=_HostFactory(fail=True))
    session_id = "next_session_2"

    response = client.post(
        "/api/rpa-agent-next/sessions", json={"identity": _identity(session_id)}
    )

    assert response.status_code == 503
    assert runtime.release_reasons == [
        (f"lease:{session_id}", "rpa_agent_next.session_closed")
    ]
    assert client.get(f"/api/rpa-agent-next/sessions/{session_id}/projection").status_code == 404


def test_next_api_rejects_legacy_identity_before_instruction_is_deserialized() -> None:
    client = _client()
    response = client.post(
        "/api/rpa-agent-next/sessions",
        json={
            "identity": _identity("next_session_3", namespace="rpa-agent/v1"),
            "legacy_trace": {"unexpected": "payload"},
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "rpa_agent_next.legacy_or_unknown_artifact"}
    }


def test_next_router_has_only_the_isolated_route_family() -> None:
    paths = {route.path for route in build_router(RpaAgentNextApiServices()).routes}
    assert all(path.startswith("/sessions") for path in paths)
    assert not any("rpa-agent" in path for path in paths)
