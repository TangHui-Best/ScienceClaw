import ast
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.rpa.harness.artifact_store import RPAHarnessArtifactStore
from backend.rpa.harness.packets import (
    FailurePacket,
    ObservationPacket,
    RPAHarnessArtifactRef,
    RPAHarnessPageState,
    RPAHarnessRedactionPolicy,
    RPAHarnessStage,
)
from backend.rpa.harness.redaction import redact_payload


def _ts() -> datetime:
    return datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)


def _is_rpa_harness_module(module: str) -> bool:
    return module == "backend.rpa.harness" or module.startswith(
        "backend.rpa.harness."
    )


def _resolve_import_from_module(node: ast.ImportFrom, package: str) -> str:
    module = node.module or ""
    if node.level == 0:
        return module

    relative_name = f"{'.' * node.level}{module}"
    return importlib.util.resolve_name(relative_name, package)


def _backend_module_name(backend_root: Path, file_path: Path) -> str:
    module_path = file_path.relative_to(backend_root).with_suffix("")
    return ".".join(("backend", *module_path.parts))


def _imports_rpa_harness(source: str, module_name: str) -> bool:
    tree = ast.parse(source)
    package = module_name.rpartition(".")[0]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_rpa_harness_module(alias.name):
                    return True

        if isinstance(node, ast.ImportFrom):
            module = _resolve_import_from_module(node, package)
            if _is_rpa_harness_module(module):
                return True
            if module == "backend.rpa":
                if any(alias.name == "harness" for alias in node.names):
                    return True

    return False


def test_stage_values_match_task_1_schema():
    assert [stage.value for stage in RPAHarnessStage] == [
        "recording",
        "snapshot",
        "planner",
        "execution",
        "repair",
        "compile",
        "replay",
    ]


def test_batch_0_does_not_import_harness_from_production_rpa_path():
    backend_root = Path(__file__).resolve().parents[1]
    root = backend_root / "rpa"
    production_files = [
        root / "recording_runtime_agent.py",
        root / "trace_recorder.py",
        root / "trace_skill_compiler.py",
        root.parent / "route" / "rpa.py",
    ]

    for file_path in production_files:
        source = file_path.read_text(encoding="utf-8")
        module_name = _backend_module_name(backend_root, file_path)
        assert not _imports_rpa_harness(source, module_name)

    prohibited_imports = [
        ("import backend.rpa.harness", "backend.rpa.trace_recorder"),
        ("import backend.rpa.harness.packets", "backend.rpa.trace_recorder"),
        ("from backend.rpa import harness", "backend.rpa.trace_recorder"),
        ("from backend.rpa.harness import packets", "backend.rpa.trace_recorder"),
        ("from . import harness", "backend.rpa.trace_recorder"),
        ("from .harness import packets", "backend.rpa.trace_recorder"),
        (
            "from .harness.packets import ObservationPacket",
            "backend.rpa.trace_recorder",
        ),
        ("from ..rpa import harness", "backend.route.rpa"),
        ("from ..rpa.harness import packets", "backend.route.rpa"),
        (
            "from ..rpa.harness.packets import ObservationPacket",
            "backend.route.rpa",
        ),
    ]
    for source, module_name in prohibited_imports:
        assert _imports_rpa_harness(source, module_name)

    allowed_non_import_references = [
        "# from backend.rpa.harness import packets",
        'message = "backend.rpa.harness is mentioned in text"',
        'message = ".harness is mentioned in text"',
        "from . import harness",
    ]
    for source in allowed_non_import_references:
        assert not _imports_rpa_harness(source, "backend.route.rpa")


def test_artifact_ref_defaults_match_task_1_schema():
    ref = RPAHarnessArtifactRef(path="artifacts/output.json")

    payload = ref.model_dump(mode="json")

    assert payload["artifact_id"].startswith("artifact-")
    assert payload["media_type"] == "application/json"
    assert payload["redacted"] is True
    assert payload["metadata"] == {}


def test_artifact_ref_requires_path():
    with pytest.raises(ValidationError):
        RPAHarnessArtifactRef()


def test_page_state_snapshot_summary_defaults_to_empty_dict():
    page_state = RPAHarnessPageState(url="https://example.test")

    assert page_state.model_dump(mode="json")["snapshot_summary"] == {}


def test_redaction_policy_contains_task_1_sensitive_keys():
    policy = RPAHarnessRedactionPolicy()

    assert policy.replacement == "<redacted>"
    assert policy.sensitive_keys == [
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "email",
        "password",
        "secret",
        "token",
    ]


def test_redaction_replaces_sensitive_keys_recursively():
    payload = {
        "authorization": "Bearer secret-token",
        "profile": {
            "email": "user@example.test",
            "name": "Visible Name",
        },
        "items": [
            {"api_key": "abc123"},
            {"label": "public"},
        ],
    }

    redacted = redact_payload(payload, RPAHarnessRedactionPolicy())

    assert redacted["authorization"] == "<redacted>"
    assert redacted["profile"]["email"] == "<redacted>"
    assert redacted["profile"]["name"] == "Visible Name"
    assert redacted["items"][0]["api_key"] == "<redacted>"
    assert redacted["items"][1]["label"] == "public"


def test_observation_packet_serializes_references_and_stage():
    packet = ObservationPacket(
        packet_id="obs-1",
        session_id="session-1",
        step_id="step-1",
        stage=RPAHarnessStage.PLANNER,
        user_instruction="open the selected project",
        started_at=_ts(),
        ended_at=_ts(),
        before_page=RPAHarnessPageState(url="https://example.test/list", title="List"),
        after_page=RPAHarnessPageState(url="https://example.test/detail", title="Detail"),
        raw_snapshot_ref=RPAHarnessArtifactRef(
            artifact_id="raw-snapshot-1",
            path="artifacts/raw_snapshot.json",
        ),
        compact_snapshot_ref=RPAHarnessArtifactRef(
            artifact_id="compact-1",
            path="artifacts/compact_snapshot.json",
            media_type="application/json",
            redacted=True,
        ),
        accepted_trace_ref=RPAHarnessArtifactRef(
            artifact_id="trace-1",
            path="artifacts/accepted_trace.json",
        ),
        generated_code_ref=RPAHarnessArtifactRef(
            artifact_id="code-1",
            path="artifacts/generated_code.py",
            media_type="text/x-python",
        ),
        compiler_output_ref=RPAHarnessArtifactRef(
            artifact_id="compiler-1",
            path="artifacts/compiler_output.json",
        ),
        execution_result={"ok": True},
        diagnostics={"model": "test-model"},
        metadata={"source": "test"},
        created_at=_ts(),
    )

    payload = packet.model_dump(mode="json")

    assert payload["packet_kind"] == "observation"
    assert payload["stage"] == "planner"
    assert payload["before_page"]["url"] == "https://example.test/list"
    assert payload["raw_snapshot_ref"]["path"] == "artifacts/raw_snapshot.json"
    assert payload["compact_snapshot_ref"]["redacted"] is True
    assert payload["accepted_trace_ref"]["artifact_id"] == "trace-1"
    assert payload["generated_code_ref"]["media_type"] == "text/x-python"
    assert payload["compiler_output_ref"]["path"] == "artifacts/compiler_output.json"
    assert payload["execution_result"] == {"ok": True}
    assert payload["metadata"] == {"source": "test"}


def test_observation_packet_defaults_optional_fields_and_id():
    packet = ObservationPacket(
        session_id="session-1",
        stage=RPAHarnessStage.SNAPSHOT,
    )

    payload = packet.model_dump(mode="json")

    assert payload["packet_id"].startswith("obs-")
    assert payload["step_id"] is None
    assert payload["user_instruction"] is None
    assert payload["started_at"] is None
    assert payload["ended_at"] is None
    assert payload["created_at"] is not None


def test_failure_packet_serializes_failure_facts():
    packet = FailurePacket(
        packet_id="fail-1",
        session_id="session-1",
        step_id="step-1",
        stage=RPAHarnessStage.EXECUTION,
        failure_type="playwright_timeout",
        user_instruction="click export",
        current_url="https://example.test/report",
        current_title="Report",
        failed_plan_summary="click the visible Export button",
        raw_error_ref=RPAHarnessArtifactRef(
            artifact_id="raw-error-1",
            path="artifacts/raw_error.txt",
            media_type="text/plain",
            redacted=True,
        ),
        failed_code_ref=RPAHarnessArtifactRef(
            artifact_id="failed-code-1",
            path="artifacts/failed_code.py",
            media_type="text/x-python",
        ),
        snapshot_after_failure_ref=RPAHarnessArtifactRef(
            artifact_id="snapshot-after-failure-1",
            path="artifacts/snapshot_after_failure.json",
        ),
        compact_snapshot_ref=RPAHarnessArtifactRef(
            artifact_id="failure-compact-1",
            path="artifacts/failure_compact_snapshot.json",
        ),
        repair_input_ref=RPAHarnessArtifactRef(
            artifact_id="repair-input-1",
            path="artifacts/repair_input.json",
        ),
        repair_output_ref=RPAHarnessArtifactRef(
            artifact_id="repair-output-1",
            path="artifacts/repair_output.json",
        ),
        attempt_trace_ref=RPAHarnessArtifactRef(
            artifact_id="attempt-trace-1",
            path="artifacts/attempt_trace.json",
        ),
        accepted_trace_ref=RPAHarnessArtifactRef(
            artifact_id="accepted-trace-1",
            path="artifacts/failure_accepted_trace.json",
        ),
        metadata={"diagnostic_mode": False},
        created_at=_ts(),
    )

    payload = packet.model_dump(mode="json")

    assert payload["packet_kind"] == "failure"
    assert payload["stage"] == "execution"
    assert payload["failure_type"] == "playwright_timeout"
    assert payload["raw_error_ref"]["path"] == "artifacts/raw_error.txt"
    assert payload["failed_code_ref"]["media_type"] == "text/x-python"
    assert (
        payload["snapshot_after_failure_ref"]["path"]
        == "artifacts/snapshot_after_failure.json"
    )
    assert payload["compact_snapshot_ref"]["artifact_id"] == "failure-compact-1"
    assert payload["repair_input_ref"]["path"] == "artifacts/repair_input.json"
    assert payload["repair_output_ref"]["path"] == "artifacts/repair_output.json"
    assert payload["attempt_trace_ref"]["path"] == "artifacts/attempt_trace.json"
    assert payload["accepted_trace_ref"]["path"] == "artifacts/failure_accepted_trace.json"


def test_failure_packet_defaults_optional_fields_and_id():
    packet = FailurePacket(
        session_id="session-1",
        stage=RPAHarnessStage.EXECUTION,
        failure_type="playwright_timeout",
    )

    payload = packet.model_dump(mode="json")

    assert payload["packet_id"].startswith("fail-")
    assert payload["step_id"] is None
    assert payload["user_instruction"] is None
    assert payload["failed_plan_summary"] is None
    assert payload["raw_error_ref"] is None
    assert payload["failed_code_ref"] is None
    assert payload["snapshot_after_failure_ref"] is None
    assert payload["compact_snapshot_ref"] is None
    assert payload["repair_input_ref"] is None
    assert payload["repair_output_ref"] is None
    assert payload["attempt_trace_ref"] is None
    assert payload["accepted_trace_ref"] is None
    assert payload["created_at"] is not None


def test_artifact_store_writes_and_reads_synthetic_failure_packet(tmp_path):
    store = RPAHarnessArtifactStore(root=tmp_path, max_packets_per_kind=10)
    packet = FailurePacket(
        packet_id="fail-write-read",
        session_id="session-1",
        step_id="step-1",
        stage=RPAHarnessStage.EXECUTION,
        failure_type="synthetic",
        user_instruction="open account with password",
        current_url="https://example.test",
        metadata={"password": "plain-secret", "visible": "kept"},
        created_at=_ts(),
    )

    packet_path = store.write_packet(packet)
    loaded = store.read_failure_packet(packet_path)

    assert packet_path.name == "packet.json"
    assert loaded.packet_id == "fail-write-read"
    assert loaded.metadata["password"] == "<redacted>"
    assert loaded.metadata["visible"] == "kept"


def test_artifact_store_rejects_outside_root_failure_packet_reads(tmp_path):
    store = RPAHarnessArtifactStore(root=tmp_path / "store", max_packets_per_kind=10)
    outside_packet = FailurePacket(
        packet_id="fail-outside",
        session_id="session-1",
        stage=RPAHarnessStage.EXECUTION,
        failure_type="synthetic",
        created_at=_ts(),
    )
    outside_path = tmp_path / "outside" / "packet.json"
    outside_path.parent.mkdir(parents=True)
    outside_path.write_text(
        outside_packet.model_dump_json(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        store.read_failure_packet(outside_path)


def test_artifact_store_rejects_outside_root_observation_packet_reads(tmp_path):
    store = RPAHarnessArtifactStore(root=tmp_path / "store", max_packets_per_kind=10)
    outside_packet = ObservationPacket(
        packet_id="obs-outside",
        session_id="session-1",
        stage=RPAHarnessStage.SNAPSHOT,
        created_at=_ts(),
    )
    outside_path = tmp_path / "outside" / "packet.json"
    outside_path.parent.mkdir(parents=True)
    outside_path.write_text(
        outside_packet.model_dump_json(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        store.read_observation_packet(outside_path)


def test_artifact_store_prunes_old_packets_by_kind(tmp_path):
    store = RPAHarnessArtifactStore(root=tmp_path, max_packets_per_kind=2)

    for index in range(3):
        packet = FailurePacket(
            packet_id=f"fail-{index}",
            session_id="session-1",
            stage=RPAHarnessStage.EXECUTION,
            failure_type="synthetic",
            created_at=datetime(2026, 5, 11, 10, index, tzinfo=timezone.utc),
        )
        store.write_packet(packet)

    packet_dirs = sorted((tmp_path / "failure").iterdir())

    assert [path.name for path in packet_dirs] == ["fail-1", "fail-2"]


@pytest.mark.parametrize("packet_id", ["../outside", "..\\outside"])
def test_artifact_store_rejects_packet_ids_that_escape_root(tmp_path, packet_id):
    store = RPAHarnessArtifactStore(root=tmp_path, max_packets_per_kind=10)
    packet = FailurePacket(
        packet_id=packet_id,
        session_id="session-1",
        stage=RPAHarnessStage.EXECUTION,
        failure_type="synthetic",
        created_at=_ts(),
    )

    with pytest.raises(ValueError):
        store.write_packet(packet)

    assert not (tmp_path.parent / "outside").exists()


def test_artifact_store_prunes_malformed_packet_dirs_before_valid_packets(tmp_path):
    store = RPAHarnessArtifactStore(root=tmp_path, max_packets_per_kind=1)
    malformed_dir = tmp_path / "failure" / "zzz-malformed"
    malformed_dir.mkdir(parents=True)
    (malformed_dir / "packet.json").write_text("{not-json", encoding="utf-8")

    packet = FailurePacket(
        packet_id="fail-valid-newer",
        session_id="session-1",
        stage=RPAHarnessStage.EXECUTION,
        failure_type="synthetic",
        created_at=datetime(2026, 5, 11, 10, 1, tzinfo=timezone.utc),
    )
    store.write_packet(packet)

    packet_dirs = sorted((tmp_path / "failure").iterdir())

    assert [path.name for path in packet_dirs] == ["fail-valid-newer"]


def test_artifact_store_prunes_missing_packet_json_dirs_before_valid_packets(tmp_path):
    store = RPAHarnessArtifactStore(root=tmp_path, max_packets_per_kind=1)
    missing_packet_dir = tmp_path / "failure" / "zzz-missing-packet"
    missing_packet_dir.mkdir(parents=True)

    packet = FailurePacket(
        packet_id="fail-valid-newer",
        session_id="session-1",
        stage=RPAHarnessStage.EXECUTION,
        failure_type="synthetic",
        created_at=datetime(2026, 5, 11, 10, 1, tzinfo=timezone.utc),
    )
    store.write_packet(packet)

    packet_dirs = sorted((tmp_path / "failure").iterdir())

    assert [path.name for path in packet_dirs] == ["fail-valid-newer"]


@pytest.mark.parametrize("packet_kind", ["../outside", "..\\outside"])
def test_artifact_store_rejects_unsafe_prune_packet_kind(tmp_path, packet_kind):
    store = RPAHarnessArtifactStore(root=tmp_path, max_packets_per_kind=1)
    outside_packet_dir = tmp_path.parent / f"outside-{tmp_path.name}" / "old-packet"
    outside_packet_dir.mkdir(parents=True)
    (outside_packet_dir / "packet.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError):
        store.prune(packet_kind)

    assert outside_packet_dir.exists()
