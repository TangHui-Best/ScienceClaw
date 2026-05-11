# RPA Harness Batch 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. The user explicitly chose subagent-driven development for the coding phase. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first fact-packet increment for the RPA harness: schemas, redaction, bounded file artifact storage, and a synthetic write/read smoke check.

**Architecture:** Add a small `backend.rpa.harness` module that is independent from the runtime recording path. `ObservationPacket` and `FailurePacket` are Pydantic v2 models; artifact storage is a local JSON-file store with explicit redaction and retention. Batch 0 does not hook into successful production recording, planner, repair, compiler, or replay flows.

**Tech Stack:** Python, Pydantic v2, pytest, pathlib, JSON files.

---

## Execution Mode

- Use `subagent-driven-development` when Batch 0 enters coding.
- Create an isolated git worktree before implementation, per the subagent workflow.
- Dispatch one fresh implementer subagent per task with the full task text and only the needed context.
- Do not dispatch multiple implementation subagents in parallel because these tasks touch shared harness files and one test file.
- After each task, run two reviews before moving on:
  - spec compliance review
  - code quality review
- The controller thread owns Harness gates, Feature updates, final verification, and integration.

## File Structure

- Create `RpaClaw/backend/rpa/harness/__init__.py`
  - Exports the Batch 0 packet models and artifact store helpers.
- Create `RpaClaw/backend/rpa/harness/packets.py`
  - Defines `RPAHarnessStage`, `RPAHarnessArtifactRef`, `RPAHarnessPageState`, `RPAHarnessRedactionPolicy`, `ObservationPacket`, and `FailurePacket`.
- Create `RpaClaw/backend/rpa/harness/redaction.py`
  - Provides recursive redaction for packet fields and artifact payloads.
- Create `RpaClaw/backend/rpa/harness/artifact_store.py`
  - Writes and reads synthetic packet JSON artifacts and prunes old packet directories by retention count.
- Create `RpaClaw/backend/tests/test_rpa_harness_packets.py`
  - Verifies model serialization, redaction, write/read round-trip, retention pruning, and no implicit production-path capture.

## Guardrails

- Do not import the harness module from `recording_runtime_agent.py`, `trace_recorder.py`, `trace_skill_compiler.py`, or `route/rpa.py` in Batch 0.
- Do not run snapshot diff, compiler evaluation, repair evaluation, or scenario evaluation in Batch 0.
- Do not reuse `rpa-eval-app` or historical golden-eval flows as baseline cases.
- Do not persist raw sensitive values in packet JSON.
- Do not create an API endpoint in Batch 0.

### Task 1: Packet Models

**Files:**
- Create: `RpaClaw/backend/rpa/harness/__init__.py`
- Create: `RpaClaw/backend/rpa/harness/packets.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_packets.py`

- [ ] **Step 1: Write the failing model serialization test**

Append this test file:

```python
from datetime import datetime, timezone

from backend.rpa.harness.packets import (
    FailurePacket,
    ObservationPacket,
    RPAHarnessArtifactRef,
    RPAHarnessPageState,
    RPAHarnessStage,
)


def _ts() -> datetime:
    return datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)


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
        compact_snapshot_ref=RPAHarnessArtifactRef(
            artifact_id="compact-1",
            path="artifacts/compact_snapshot.json",
            media_type="application/json",
            redacted=True,
        ),
        execution_result={"ok": True},
        diagnostics={"model": "test-model"},
    )

    payload = packet.model_dump(mode="json")

    assert payload["packet_kind"] == "observation"
    assert payload["stage"] == "planner"
    assert payload["before_page"]["url"] == "https://example.test/list"
    assert payload["compact_snapshot_ref"]["redacted"] is True
    assert payload["execution_result"] == {"ok": True}


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
        metadata={"diagnostic_mode": False},
        created_at=_ts(),
    )

    payload = packet.model_dump(mode="json")

    assert payload["packet_kind"] == "failure"
    assert payload["stage"] == "execution"
    assert payload["failure_type"] == "playwright_timeout"
    assert payload["raw_error_ref"]["path"] == "artifacts/raw_error.txt"
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_harness_packets.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.rpa.harness'`.

- [ ] **Step 3: Implement packet models**

Create `RpaClaw/backend/rpa/harness/packets.py`:

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class RPAHarnessStage(str, Enum):
    RECORDING = "recording"
    SNAPSHOT = "snapshot"
    PLANNER = "planner"
    EXECUTION = "execution"
    REPAIR = "repair"
    COMPILE = "compile"
    REPLAY = "replay"


class RPAHarnessArtifactRef(BaseModel):
    artifact_id: str = Field(default_factory=lambda: f"artifact-{uuid4().hex}")
    path: str
    media_type: str = "application/json"
    redacted: bool = True
    sha256: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RPAHarnessPageState(BaseModel):
    url: str = ""
    title: str = ""
    snapshot_summary: Dict[str, Any] = Field(default_factory=dict)


class RPAHarnessRedactionPolicy(BaseModel):
    enabled: bool = True
    replacement: str = "<redacted>"
    sensitive_keys: list[str] = Field(
        default_factory=lambda: [
            "access_token",
            "api_key",
            "authorization",
            "cookie",
            "email",
            "password",
            "secret",
            "token",
        ]
    )


class ObservationPacket(BaseModel):
    packet_kind: Literal["observation"] = "observation"
    packet_id: str = Field(default_factory=lambda: f"obs-{uuid4().hex}")
    session_id: str
    step_id: Optional[str] = None
    stage: RPAHarnessStage
    user_instruction: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    before_page: RPAHarnessPageState = Field(default_factory=RPAHarnessPageState)
    after_page: RPAHarnessPageState = Field(default_factory=RPAHarnessPageState)
    raw_snapshot_ref: Optional[RPAHarnessArtifactRef] = None
    compact_snapshot_ref: Optional[RPAHarnessArtifactRef] = None
    accepted_trace_ref: Optional[RPAHarnessArtifactRef] = None
    generated_code_ref: Optional[RPAHarnessArtifactRef] = None
    compiler_output_ref: Optional[RPAHarnessArtifactRef] = None
    execution_result: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class FailurePacket(BaseModel):
    packet_kind: Literal["failure"] = "failure"
    packet_id: str = Field(default_factory=lambda: f"fail-{uuid4().hex}")
    session_id: str
    step_id: Optional[str] = None
    stage: RPAHarnessStage
    failure_type: str
    user_instruction: Optional[str] = None
    current_url: str = ""
    current_title: str = ""
    failed_plan_summary: Optional[str] = None
    failed_code_ref: Optional[RPAHarnessArtifactRef] = None
    raw_error_ref: Optional[RPAHarnessArtifactRef] = None
    snapshot_after_failure_ref: Optional[RPAHarnessArtifactRef] = None
    compact_snapshot_ref: Optional[RPAHarnessArtifactRef] = None
    repair_input_ref: Optional[RPAHarnessArtifactRef] = None
    repair_output_ref: Optional[RPAHarnessArtifactRef] = None
    attempt_trace_ref: Optional[RPAHarnessArtifactRef] = None
    accepted_trace_ref: Optional[RPAHarnessArtifactRef] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
```

Create `RpaClaw/backend/rpa/harness/__init__.py`:

```python
from .artifact_store import RPAHarnessArtifactStore
from .packets import (
    FailurePacket,
    ObservationPacket,
    RPAHarnessArtifactRef,
    RPAHarnessPageState,
    RPAHarnessRedactionPolicy,
    RPAHarnessStage,
)

__all__ = [
    "FailurePacket",
    "ObservationPacket",
    "RPAHarnessArtifactRef",
    "RPAHarnessArtifactStore",
    "RPAHarnessPageState",
    "RPAHarnessRedactionPolicy",
    "RPAHarnessStage",
]
```

- [ ] **Step 4: Run the model tests**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_harness_packets.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `backend.rpa.harness.artifact_store`, because `__init__.py` exports the store before Task 3 creates it.

### Task 2: Redaction

**Files:**
- Create: `RpaClaw/backend/rpa/harness/redaction.py`
- Modify: `RpaClaw/backend/tests/test_rpa_harness_packets.py`

- [ ] **Step 1: Write the failing redaction test**

Append to `RpaClaw/backend/tests/test_rpa_harness_packets.py`:

```python
from backend.rpa.harness.packets import RPAHarnessRedactionPolicy
from backend.rpa.harness.redaction import redact_payload


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
```

- [ ] **Step 2: Run the failing redaction test**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_harness_packets.py::test_redaction_replaces_sensitive_keys_recursively -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.rpa.harness.redaction'`.

- [ ] **Step 3: Implement recursive redaction**

Create `RpaClaw/backend/rpa/harness/redaction.py`:

```python
from __future__ import annotations

from typing import Any

from .packets import RPAHarnessRedactionPolicy


def redact_payload(payload: Any, policy: RPAHarnessRedactionPolicy | None = None) -> Any:
    active_policy = policy or RPAHarnessRedactionPolicy()
    if not active_policy.enabled:
        return payload

    sensitive_keys = {key.lower() for key in active_policy.sensitive_keys}

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                if str(key).lower() in sensitive_keys:
                    redacted[str(key)] = active_policy.replacement
                else:
                    redacted[str(key)] = visit(item)
            return redacted
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    return visit(payload)
```

- [ ] **Step 4: Run the redaction test**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_harness_packets.py::test_redaction_replaces_sensitive_keys_recursively -q
```

Expected: PASS.

### Task 3: Artifact Store And Retention

**Files:**
- Create: `RpaClaw/backend/rpa/harness/artifact_store.py`
- Modify: `RpaClaw/backend/tests/test_rpa_harness_packets.py`

- [ ] **Step 1: Write the failing write/read and retention tests**

Append to `RpaClaw/backend/tests/test_rpa_harness_packets.py`:

```python
from backend.rpa.harness.artifact_store import RPAHarnessArtifactStore


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
```

- [ ] **Step 2: Run the failing store tests**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_harness_packets.py::test_artifact_store_writes_and_reads_synthetic_failure_packet RpaClaw/backend/tests/test_rpa_harness_packets.py::test_artifact_store_prunes_old_packets_by_kind -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.rpa.harness.artifact_store'`.

- [ ] **Step 3: Implement local JSON artifact store**

Create `RpaClaw/backend/rpa/harness/artifact_store.py`:

```python
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Union

from pydantic import BaseModel

from .packets import FailurePacket, ObservationPacket, RPAHarnessRedactionPolicy
from .redaction import redact_payload

Packet = Union[ObservationPacket, FailurePacket]


class RPAHarnessArtifactStore:
    def __init__(
        self,
        root: str | Path,
        max_packets_per_kind: int = 100,
        redaction_policy: RPAHarnessRedactionPolicy | None = None,
    ) -> None:
        self.root = Path(root)
        self.max_packets_per_kind = max(1, max_packets_per_kind)
        self.redaction_policy = redaction_policy or RPAHarnessRedactionPolicy()

    def write_packet(self, packet: Packet) -> Path:
        packet_dir = self.root / packet.packet_kind / packet.packet_id
        packet_dir.mkdir(parents=True, exist_ok=True)
        packet_path = packet_dir / "packet.json"
        payload = self._redacted_model_dump(packet)
        packet_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.prune(packet.packet_kind)
        return packet_path

    def read_observation_packet(self, path: str | Path) -> ObservationPacket:
        return ObservationPacket.model_validate(self._read_json(path))

    def read_failure_packet(self, path: str | Path) -> FailurePacket:
        return FailurePacket.model_validate(self._read_json(path))

    def prune(self, packet_kind: str) -> None:
        kind_dir = self.root / packet_kind
        if not kind_dir.exists():
            return
        packet_dirs = [path for path in kind_dir.iterdir() if path.is_dir()]
        if len(packet_dirs) <= self.max_packets_per_kind:
            return

        def sort_key(path: Path) -> tuple[str, str]:
            packet_path = path / "packet.json"
            if not packet_path.exists():
                return ("", path.name)
            try:
                payload = self._read_json(packet_path)
            except json.JSONDecodeError:
                return ("", path.name)
            return (str(payload.get("created_at") or ""), path.name)

        for packet_dir in sorted(packet_dirs, key=sort_key)[: -self.max_packets_per_kind]:
            shutil.rmtree(packet_dir)

    def _redacted_model_dump(self, packet: BaseModel) -> dict:
        payload = packet.model_dump(mode="json")
        redacted = redact_payload(payload, self.redaction_policy)
        if not isinstance(redacted, dict):
            raise TypeError("packet model dump must produce a dictionary")
        return redacted

    @staticmethod
    def _read_json(path: str | Path) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run the full Batch 0 packet tests**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_harness_packets.py -q
```

Expected: PASS.

### Task 4: Production Path Isolation Check

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_harness_packets.py`

- [ ] **Step 1: Write the isolation test**

Append to `RpaClaw/backend/tests/test_rpa_harness_packets.py`:

```python
from pathlib import Path


def test_batch_0_does_not_import_harness_from_production_rpa_path():
    root = Path(__file__).resolve().parents[1] / "rpa"
    production_files = [
        root / "recording_runtime_agent.py",
        root / "trace_recorder.py",
        root / "trace_skill_compiler.py",
        root.parent / "route" / "rpa.py",
    ]

    for file_path in production_files:
        source = file_path.read_text(encoding="utf-8")
        assert "rpa.harness" not in source
        assert ".harness" not in source
```

- [ ] **Step 2: Run the isolation test**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_harness_packets.py::test_batch_0_does_not_import_harness_from_production_rpa_path -q
```

Expected: PASS.

- [ ] **Step 3: Run the focused RPA smoke set**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_harness_packets.py -q
```

Expected: PASS.

### Task 5: Feature Evidence Update

**Files:**
- Modify: `docs/features/F001-rpa-harness-engineering.md`

- [ ] **Step 1: Update links and evidence after tests pass**

Add this link under `## Links`:

```markdown
- Batch 0 plan: [RPA Harness Batch 0 Implementation Plan](../superpowers/plans/2026-05-11-rpa-harness-batch-0.md)
```

Add these bullets under `## Evidence`:

```markdown
- 2026-05-11: Created Batch 0 implementation plan at
  `docs/superpowers/plans/2026-05-11-rpa-harness-batch-0.md`.
- 2026-05-11: Batch 0 implemented packet schemas, redaction, local artifact
  write/read, retention pruning, and production-path isolation checks.
- 2026-05-11: Verified with
  `$env:PYTHONPATH="RpaClaw"; pytest RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_harness_packets.py -q`.
```

Replace `## Next Step` with:

```markdown
## Next Step

Proceed to Batch 1 only after at least one real RPA failure packet shape is
reviewed for redaction quality and storage cost. Do not auto-promote captured
packets into harness cases.
```

- [ ] **Step 2: Run Harness knowledge check**

Run:

```powershell
python C:\Users\HUAWEI\.codex\skills\harness-knowledge-capture\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs
```

Expected: `Errors: 0`.

## Self-Review

- Spec coverage: Batch 0 acceptance is covered by packet schemas, redaction policy, synthetic write/read, retention pruning, and isolation from production success path.
- Placeholder scan: no `TBD`, `TODO`, `implement later`, or unspecified test instructions are present.
- Type consistency: packet class names, enum values, artifact refs, and store method names are consistent across tasks.
