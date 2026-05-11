---
doc_kind: plan
status: completed
created: 2026-05-11
updated: 2026-05-11
owner: rpa
scope: rpa-harness
feature_ids: [F001]
---

# RPA Harness Batch 1 Implementation Plan

## Goal

Build the smallest real-flow failure capture loop for trace-first recording:
when recording-time planner, execution, or repair fails, emit a redacted
`FailurePacket` and packet-local artifacts into the bounded local artifact
store.

## Scope

In scope:

- Add packet-local artifact writes to `RPAHarnessArtifactStore`.
- Add a failure capture helper under `backend.rpa.harness`.
- Wire `RecordingRuntimeAgent` failure branches to emit facts.
- Prove ordinary successful recording steps do not write failure packets.
- Keep redaction, retention, and path containment active.

Out of scope:

- Compile/replay capture.
- Harness case promotion.
- Evaluators, dashboards, reports, or raw-vs-compact diff scoring.
- Multi-round repair or planner strategy changes.
- Site-specific rules or historical golden/eval baselines.

## Implementation Tasks

### Task 1: Packet-Local Artifact Writes

Files:

- `RpaClaw/backend/rpa/harness/artifact_store.py`
- `RpaClaw/backend/tests/test_rpa_harness_packets.py`

Steps:

- Add failing tests for `write_packet_artifact`.
- Verify unsafe artifact names cannot escape the artifact root.
- Implement JSON/text artifact writes under
  `<root>/<packet_kind>/<packet_id>/artifacts/`.
- Return `RPAHarnessArtifactRef` paths relative to the artifact root.

### Task 2: Failure Capture Helper

Files:

- `RpaClaw/backend/rpa/harness/failure_capture.py`
- `RpaClaw/backend/config.py`
- `RpaClaw/backend/tests/test_rpa_harness_packets.py`

Steps:

- Add failing tests for `capture_rpa_failure_packet`.
- Add `RPA_HARNESS_ARTIFACT_DIR` and `RPA_HARNESS_MAX_FAILURE_PACKETS`
  settings.
- Construct `FailurePacket` with stage, failure type, session/step,
  instruction, current page facts, plan summary, artifact refs, and metadata.
- Write raw error, failed code, snapshot, compact snapshot, repair input, and
  repair output artifacts only when facts are available.
- Catch capture write failures so diagnostics never break the recording path.

### Task 3: Recording Runtime Wiring

Files:

- `RpaClaw/backend/rpa/recording_runtime_agent.py`
- `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`
- `RpaClaw/backend/tests/test_rpa_harness_packets.py`

Steps:

- Add tests proving pure success writes no packet.
- Add tests proving initial execution failure writes an execution-stage packet,
  even if one allowed repair succeeds.
- Add tests proving repair execution failure writes a repair-stage packet.
- Call the helper only in existing planner, execution, and repair failure
  branches.
- Keep `trace_recorder.py`, `trace_skill_compiler.py`, and `route/rpa.py` free
  of harness imports for this batch.

## Verification

Required commands:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_harness_packets.py -q --basetemp .pytest-tmp-batch1
pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_success_does_not_write_failure_packet RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_writes_execution_failure_packet_before_repair RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_writes_repair_failure_packet -q --basetemp .pytest-tmp-batch1-runtime-focused
```

## Acceptance Checks

- Failure packets identify stage, failure type, raw error ref, page URL/title,
  user instruction, and failed plan summary.
- Redaction applies to packet metadata and packet-local artifacts.
- Retention remains bounded through `RPAHarnessArtifactStore.write_packet`.
- Ordinary successful recording paths write no failure packet.
- Runtime behavior remains trace-first and single-repair.
