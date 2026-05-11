---
id: F001
doc_kind: feature
status: active
created: 2026-05-11
updated: 2026-05-11
---

# F001: RPA Harness Engineering

## Goal

Build a real-flow RPA harness that turns production and development failures
into observable, reproducible, attributable, and regression-protected engineering
assets.

The feature protects the trace-first RPA direction by keeping the production
path focused on factual recording while moving heavy evaluation into offline
development, CI, and diagnosis flows.

## Current Status

Active implementation stage. The architecture guideline is written. Batch 0
established packet, redaction, artifact storage, retention, and
production-path isolation checks; Batch 1 added recording-time failure capture;
Batch 2 added the first offline DOM morphology harness for snapshot
compression; Batch 3 adds task-shape-aware raw-vs-compact snapshot diffing.

Current accepted direction:

- production emits facts only on failure or explicit diagnostic capture
- harness evaluation runs offline, in development, or in CI
- the first corpus must come from real RPA usage, not historical golden-eval
  flows that diverge from the current user path
- DOM morphology cases are first-class harness assets because snapshot
  compression quality is central to RPA usefulness

## Links

- Spec: [RPA Harness Engineering](../rpa/rpa-harness-engineering.md)
- Related architecture: [Trace-first Architecture](../rpa/trace-first-architecture.md)
- Related repair policy: [Failure Repair Policy](../rpa/failure-repair-policy.md)
- Related compiler strategy: [TraceSkillCompiler Generalization](../rpa/trace-skill-compiler-generalization.md)
- Design index: [Design Document Status](../DESIGN_STATUS.md)
- Batch 0 plan: [RPA Harness Batch 0 Implementation Plan](../rpa/rpa-harness-batch-0-implementation-plan.md)
- Batch 1 plan: [RPA Harness Batch 1 Implementation Plan](../rpa/rpa-harness-batch-1-implementation-plan.md)
- Batch 2 plan: [RPA Harness Batch 2 Implementation Plan](../rpa/rpa-harness-batch-2-implementation-plan.md)
- Batch 3 plan: [RPA Harness Batch 3 Implementation Plan](../rpa/rpa-harness-batch-3-implementation-plan.md)

## Acceptance Criteria

- `ObservationPacket` and `FailurePacket` schemas exist with redaction and
  retention rules.
- Real RPA failures can be captured as failure packets without unbounded endpoint
  disk growth.
- Failure packets require triage before promotion into harness cases.
- DOM morphology cases cover at least key/value, table, candidate list/card,
  form, and iframe structures.
- Snapshot harness can distinguish missing raw evidence from compact snapshot
  evidence loss.
- Compiler harness guards dataflow, observed-value de-hardcoding, runtime AI
  preservation, and URL base/suffix generalization.
- Repair harness verifies fact completeness and single-repair policy boundaries.
- Scenario harness contains a small set of real SOP smoke flows and does not
  replace layer-specific harness cases.
- Optional observability adapters remain outside harness core until license
  review is complete.

## Vision Gate

Outcome: pass

Original intent:

- Build a real-flow RPA harness to prevent "fix A, break B" regressions.
- Keep production lightweight: emit facts only, evaluate offline.
- Treat DOM morphology and snapshot compression as first-class harness assets.
- Do not reuse historical golden-eval flows as the baseline when they diverge
  from real user flow.

Alignment:

- The current spec defines failure packets, observation packets, DOM morphology
  corpus, snapshot diff, compiler, repair, and scenario harness layers.
- The design keeps trace-first recording intact and keeps heavy evaluation
  outside the production path.

Drift risks:

- Turning harness into a dashboard/platform before local domain cases are
  stable.
- Letting production diagnostics grow into an unbounded corpus.
- Promoting failure packets into cases without triage.
- Reintroducing site-specific rules or contract-first recording.

Required next action:

- Proceed to Batch 0 implementation planning.

## Evidence

- 2026-05-11: Created active design guideline at
  `docs/rpa/rpa-harness-engineering.md`.
- 2026-05-11: Registered the guideline in `docs/DESIGN_STATUS.md`.
- 2026-05-11: Recorded Entry Vision Gate in this Feature page.
- 2026-05-11: Created Batch 0 implementation plan at
  `docs/rpa/rpa-harness-batch-0-implementation-plan.md`.
- 2026-05-11: Confirmed Batch 0 coding should use
  `subagent-driven-development` with per-task implementer and review gates.
- 2026-05-11: Batch 0 implemented packet schemas, redaction, local artifact
  write/read, retention pruning, path containment checks, and production-path
  isolation checks.
- 2026-05-11: Verified with
  `$env:PYTHONPATH="RpaClaw"; pytest RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_harness_packets.py -q --basetemp .pytest-tmp`.
- 2026-05-11: Created Batch 1 implementation plan at
  `docs/rpa/rpa-harness-batch-1-implementation-plan.md`.
- 2026-05-11: Batch 1 implemented the first recording-time failure capture
  loop: planner/execution/repair failures emit redacted `FailurePacket`
  artifacts while pure successful recording paths write no failure packet.
- 2026-05-11: Verified Batch 1 packet and trace-model checks with
  `$env:PYTHONPATH="RpaClaw"; pytest RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_harness_packets.py -q --basetemp .pytest-tmp-batch1`
  (`31 passed`), and verified the runtime failure-capture tests with
  `$env:PYTHONPATH="RpaClaw"; pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_success_does_not_write_failure_packet RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_planner_failure_packet_includes_snapshots RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_writes_execution_failure_packet_before_repair RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_writes_repair_failure_packet -q --basetemp .pytest-tmp-batch1-runtime-focused`
  (`4 passed`).
- 2026-05-11: Independent review found two Batch 1 gaps: text/string redaction
  was weaker than artifact `redacted=True` implied, and initial planner
  failures omitted already-available snapshot evidence. Batch 1 fixed both and
  added regression coverage for URL/code/email/sensitive label-value redaction
  and planner-failure snapshot refs.
- 2026-05-11: Follow-up review found generated-code redaction still missed
  common Playwright and dict-literal shapes such as password fills and
  `{"password": "..."}`. Batch 1 added regression coverage and redaction for
  those text forms, then re-verified packet and runtime focused tests.
- 2026-05-11: Re-ran Batch 1 verification with the project virtual
  environment at `.venv\Scripts\python.exe`: packet/trace-model checks passed
  with `31 passed`, and full
  `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py` passed with
  `63 passed`.
- 2026-05-11: Created Batch 2 implementation plan at
  `docs/rpa/rpa-harness-batch-2-implementation-plan.md`.
- 2026-05-11: Batch 2 implemented the first DOM morphology harness under
  `tests/rpa_harness`: curated cases for key/value split siblings, table row
  actions, candidate cards, form fields, and iframe content; a
  `DomMorphologyEvaluator`; and `python -m tests.rpa_harness.run dom`.
- 2026-05-11: Verified Batch 2 with
  `$env:PYTHONPATH="RpaClaw"; ..\..\.venv\Scripts\python.exe -m pytest tests/rpa_harness RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py -q --basetemp .pytest-tmp-batch2`
  (`26 passed`) and
  `$env:PYTHONPATH="RpaClaw"; ..\..\.venv\Scripts\python.exe -m tests.rpa_harness.run dom`
  (`DOM morphology cases: 5`, `pass: 5`, `fail: 0`).
- 2026-05-11: Created Batch 3 implementation plan at
  `docs/rpa/rpa-harness-batch-3-implementation-plan.md`.
- 2026-05-11: Batch 3 implemented task-shape-aware Snapshot Diff Harness under
  `tests/rpa_harness/evaluators/snapshot_diff.py`, reusing the five Batch 2 DOM
  morphology cases and adding `python -m tests.rpa_harness.run snapshot`.
- 2026-05-11: Verified Batch 3 with
  `$env:PYTHONPATH="RpaClaw"; ..\..\.venv\Scripts\python.exe -m pytest tests/rpa_harness RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py -q --basetemp .pytest-tmp-batch3`
  (`30 passed`),
  `$env:PYTHONPATH="RpaClaw"; ..\..\.venv\Scripts\python.exe -m tests.rpa_harness.run dom`
  (`DOM morphology cases: 5`, `pass: 5`, `fail: 0`), and
  `$env:PYTHONPATH="RpaClaw"; ..\..\.venv\Scripts\python.exe -m tests.rpa_harness.run snapshot`
  (`Snapshot diff cases: 5`, `pass: 5`, `fail: 0`).

## Next Step

Proceed to Batch 4 compiler harness. Keep the Batch 3 rule: snapshot failures
must report the missing fact key and attribution layer before planner prompt,
selector, repair, or compiler changes are considered.
