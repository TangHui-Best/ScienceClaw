---
doc_kind: plan
status: completed
created: 2026-05-11
updated: 2026-05-11
owner: rpa
scope: rpa-harness
feature_ids: [F001]
---

# RPA Harness Batch 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a task-shape-aware Snapshot Diff Harness that reports exactly which task-relevant raw facts are absent from compact snapshots.

**Architecture:** Reuse the Batch 2 DOM morphology cases as the first snapshot-diff corpus. Add a test-only evaluator under `tests/rpa_harness/evaluators` that extracts structured facts from raw snapshots and compact snapshots, compares expected fact keys by task shape, and reports `raw_missing` or `compact_loss` with precise missing paths. Extend the existing CLI runner with `snapshot`.

**Tech Stack:** Python, pytest, JSON fixtures, `backend.rpa.snapshot_compression`.

---

## Start Gate

Start Gate: ready

Task class:
- non-trivial

Risk triggers:
- Builds on Batch 2 case format and future-agent Harness memory.
- Changes diagnostic behavior in test harness, though not production runtime.
- Must preserve the project rule: compare raw and compact snapshots before fixing planner prompts.

Required pre-work:
- Reuse F001 and `docs/rpa/rpa-harness-engineering.md` as Vision Anchors.
- Continue from the Batch 2 worktree because Batch 3 depends on Batch 2's uncommitted case corpus.
- Switch the worktree branch to `codex/rpa-harness-batch-3`.

Allowed next action:
- Implement offline Snapshot Diff Harness only.

## Entry Vision Gate

Vision Gate: ready to implement

Mode:
- Entry Gate

Original intent:
- Turn raw-vs-compact comparison into a precise diagnostic layer so snapshot compression fixes target the right structure before planner prompt changes.

Alignment:
- The plan reuses curated structural cases, keeps evaluation offline, and adds structured diff output.
- The plan does not alter recording, repair, planner, compiler, replay, or production APIs.

Drift risks:
- Rebuilding a generic observability platform instead of a local RPA snapshot diff.
- Treating all task shapes as flat text and missing candidate-set or row-action relationships.
- Reporting compact loss when raw evidence was already missing.

Vision Anchor:
- `docs/features/F001-rpa-harness-engineering.md`
- `docs/rpa/rpa-harness-engineering.md`

Reviewer policy:
- independent recommended before final handoff.

Optional lenses used:
- Engineering

Acceptance-criteria drift:
- None. Batch 3 is specifically the Snapshot Diff Harness described in F001.

Required next action:
- Execute TDD tasks below.

## File Structure

- Create `tests/rpa_harness/evaluators/snapshot_diff.py`
  - Defines structured facts, a task-shape-aware extractor, diff results, summary, and evaluator.
- Modify `tests/rpa_harness/evaluators/__init__.py`
  - Exports Snapshot Diff evaluator types.
- Modify `tests/rpa_harness/run.py`
  - Adds `snapshot` command and keeps `dom` unchanged.
- Create `tests/rpa_harness/test_snapshot_diff_evaluator.py`
  - Tests raw-missing, compact-loss, task-shape paths, case reuse, and runner output.
- Modify `docs/features/F001-rpa-harness-engineering.md`
  - Link Batch 3 plan and record verification evidence after tests pass.

## Fact Model

Use stable fact keys so failed reports are actionable:

```text
detail.field.<label>
detail.value.<label>
detail.locator.<label>
table.column.<header>
table.row.<row_text>
table.action.<label>
candidate.title.<title>
candidate.metadata.<title>
candidate.locator.<title>
form.field.<label>
form.placeholder.<label>
form.locator.<label>
iframe.frame_path.<path>
```

## Tasks

### Task 1: Snapshot Diff Contract

Files:
- Create: `tests/rpa_harness/test_snapshot_diff_evaluator.py`
- Create: `tests/rpa_harness/evaluators/snapshot_diff.py`
- Modify: `tests/rpa_harness/evaluators/__init__.py`

- [ ] Step 1: Write failing tests for `SnapshotDiffEvaluator` attribution:
  - `raw_missing` wins when raw snapshot lacks an expected fact key.
  - `compact_loss` reports missing compact paths when raw has the fact.
- [ ] Step 2: Run focused tests and verify failure is due to missing module.
- [ ] Step 3: Implement `SnapshotFact`, `SnapshotDiffResult`, `SnapshotDiffSummary`, `SnapshotFactExtractor`, and `SnapshotDiffEvaluator`.
- [ ] Step 4: Keep extraction task-shape aware for detail, table, candidate, form, and iframe cases.
- [ ] Step 5: Run focused tests and confirm pass.

### Task 2: Case Reuse And Runner

Files:
- Modify: `tests/rpa_harness/test_snapshot_diff_evaluator.py`
- Modify: `tests/rpa_harness/run.py`

- [ ] Step 1: Write failing tests proving the Batch 2 five-case corpus passes the snapshot diff evaluator.
- [ ] Step 2: Add `snapshot` runner command.
- [ ] Step 3: Runner output must include case count, pass/fail summary, failed case name, missing fact keys, and attribution layer.
- [ ] Step 4: Run `python -m tests.rpa_harness.run snapshot` and confirm five cases pass.

### Task 3: Verification And Feature Evidence

Files:
- Modify: `docs/features/F001-rpa-harness-engineering.md`

- [ ] Step 1: Run focused tests:

```powershell
$env:PYTHONPATH="RpaClaw"
..\..\.venv\Scripts\python.exe -m pytest tests/rpa_harness RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py -q --basetemp .pytest-tmp-batch3
```

- [ ] Step 2: Run runners:

```powershell
$env:PYTHONPATH="RpaClaw"
..\..\.venv\Scripts\python.exe -m tests.rpa_harness.run dom
..\..\.venv\Scripts\python.exe -m tests.rpa_harness.run snapshot
```

- [ ] Step 3: Update F001 links, evidence, and next step.
- [ ] Step 4: Run Harness knowledge check.

## Self-Review

- Spec coverage: The plan covers raw-vs-compact diff, task-shape-aware fact keys, runner output, and Feature evidence.
- Placeholder scan: No `TBD`, `TODO`, or undefined verification path remains.
- Scope check: The plan excludes dashboarding, production-path evaluation, auto-promotion, site rules, prompt fixes, and repair changes.
- Type consistency: Fact keys, result fields, and runner output are stable enough for Batch 4+ consumers.
