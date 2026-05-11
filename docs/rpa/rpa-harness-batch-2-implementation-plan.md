---
doc_kind: plan
status: completed
created: 2026-05-11
updated: 2026-05-11
owner: rpa
scope: rpa-harness
feature_ids: [F001]
---

# RPA Harness Batch 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a DOM morphology harness that proves task-relevant facts present in raw snapshots survive snapshot compression.

**Architecture:** Add a test-only harness package under `tests/rpa_harness` with versioned morphology cases, a small evaluator, and a CLI runner. Cases are structural rather than site-specific, and the evaluator calls the existing `compact_recording_snapshot` function without changing the production recording path.

**Tech Stack:** Python, pytest, JSON fixtures, `backend.rpa.snapshot_compression`.

---

## Start Gate

Start Gate: needs retrieval, then ready

Task class:
- non-trivial

Risk triggers:
- Multi-file harness increment with future-agent recovery needs.
- Must preserve trace-first production boundaries.
- Must distinguish raw evidence absence from compact snapshot loss.

Required pre-work:
- Read F001, active RPA harness design, Batch 0/1 plans, `AGENTS.md`, and snapshot compression tests.
- Create isolated worktree `E:\Work-Project\OtherWork\ScienceClaw\.worktrees\rpa-harness-batch-2`.
- Fast-forward Batch 2 worktree onto `codex/rpa-harness-batch-1` because local `codex/rpa-trace-first-recording` had not yet incorporated Batch 1.

Allowed next action:
- Implement Batch 2 offline harness only.

## Entry Vision Gate

Vision Gate: ready to implement

Mode:
- Entry Gate

Original intent:
- Make DOM structure patterns reproducible and attributable so snapshot compression fixes start from raw-vs-compact evidence, not planner prompt guesswork.

Alignment:
- The plan creates curated, structural cases and an offline evaluator.
- It does not expand failure packet capture, production recording, repair count, dashboarding, or site rules.

Drift risks:
- Overbuilding a generic eval platform before the five required morphology cases exist.
- Turning candidate selection into another TopK detail-region problem.
- Treating raw snapshots as always trustworthy instead of reporting `raw_missing`.

Vision Anchor:
- `docs/features/F001-rpa-harness-engineering.md`
- `docs/rpa/rpa-harness-engineering.md`

Reviewer policy:
- independent recommended for later review; self-review is acceptable for the initial implementation checkpoint.

Optional lenses used:
- Engineering

Acceptance-criteria drift:
- None. The implementation deliberately stops at offline DOM morphology cases and runner output.

Required next action:
- Execute TDD tasks below.

## File Structure

- Create `tests/rpa_harness/__init__.py`
  - Marks the harness package importable by `python -m tests.rpa_harness.run`.
- Create `tests/rpa_harness/cases/dom_morphology/*/case.json`
  - Stores case metadata, raw snapshot fixture, expected facts, locator expectations, and guarded failure mode.
- Create `tests/rpa_harness/evaluators/__init__.py`
  - Exports evaluator types.
- Create `tests/rpa_harness/evaluators/dom_morphology.py`
  - Loads cases, runs `compact_recording_snapshot`, compares raw and compact facts, and reports `raw_missing` or `compact_loss`.
- Create `tests/rpa_harness/run.py`
  - Provides `python -m tests.rpa_harness.run dom`.
- Create `tests/rpa_harness/test_dom_morphology_evaluator.py`
  - TDD tests for attribution, summary output, and the five required case shapes.
- Modify `docs/features/F001-rpa-harness-engineering.md`
  - Link Batch 2 plan and record verification evidence after tests pass.

## Case Metadata Shape

Each `case.json` uses this stable shape:

```json
{
  "case_id": "key_value_split_siblings",
  "case_type": "dom_morphology",
  "title": "Key/value split siblings",
  "task_shape": "detail_extraction",
  "instruction": "Extract the invoice status and owner",
  "source": "curated_structural_fixture",
  "raw_snapshot": {},
  "expected_raw_facts": ["Invoice Status", "Approved"],
  "expected_compact_facts": ["Invoice Status", "Approved"],
  "expected_semantic_view": {
    "kind": "label_value_group"
  },
  "expected_locator_preservation": [
    "page.get_by_text('Invoice Status')"
  ],
  "guarded_failure_mode": "raw snapshot contains split sibling facts but compression drops the value"
}
```

## Tasks

### Task 1: Evaluator Contract

Files:
- Create: `tests/rpa_harness/test_dom_morphology_evaluator.py`
- Create: `tests/rpa_harness/evaluators/dom_morphology.py`
- Create: `tests/rpa_harness/evaluators/__init__.py`
- Create: `tests/rpa_harness/__init__.py`

- [ ] Step 1: Write failing tests for `DomMorphologyEvaluator` attribution.
- [ ] Step 2: Run the focused test and confirm failure is due to missing evaluator.
- [ ] Step 3: Implement dataclasses for case result and summary.
- [ ] Step 4: Implement raw and compact text flattening plus attribution:
  - `passed` when all raw and compact facts are present.
  - `raw_missing` when at least one expected raw fact is absent from raw snapshot text.
  - `compact_loss` when raw has the fact but compact output loses it.
- [ ] Step 5: Run focused tests and confirm pass.

### Task 2: First Case And Runner

Files:
- Create: `tests/rpa_harness/cases/dom_morphology/key_value_split_siblings/case.json`
- Create: `tests/rpa_harness/run.py`
- Modify: `tests/rpa_harness/test_dom_morphology_evaluator.py`

- [ ] Step 1: Write failing test that loads the key/value case and expects one pass.
- [ ] Step 2: Create a raw snapshot fixture with split sibling label/value nodes.
- [ ] Step 3: Implement case discovery and runner `dom` command.
- [ ] Step 4: Run `python -m tests.rpa_harness.run dom` and confirm it prints case count and pass summary.

### Task 3: Required Morphology Coverage

Files:
- Create: `tests/rpa_harness/cases/dom_morphology/table_with_row_actions/case.json`
- Create: `tests/rpa_harness/cases/dom_morphology/candidate_cards/case.json`
- Create: `tests/rpa_harness/cases/dom_morphology/form_fields/case.json`
- Create: `tests/rpa_harness/cases/dom_morphology/iframe_content/case.json`
- Modify: `tests/rpa_harness/test_dom_morphology_evaluator.py`

- [ ] Step 1: Write failing test that exactly the five required case IDs are present.
- [ ] Step 2: Add table case with headers, row facts, and row-level action locator.
- [ ] Step 3: Add candidate card/list case with multiple comparable candidates and primary action locators.
- [ ] Step 4: Add form field case with visible editable controls and labels.
- [ ] Step 5: Add iframe case with frame path facts and locators.
- [ ] Step 6: Run the evaluator tests and runner.

### Task 4: Verification And Feature Evidence

Files:
- Modify: `docs/features/F001-rpa-harness-engineering.md`

- [ ] Step 1: Run focused tests:

```powershell
$env:PYTHONPATH="RpaClaw"
..\..\.venv\Scripts\python.exe -m pytest tests/rpa_harness RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py -q --basetemp .pytest-tmp-batch2
```

- [ ] Step 2: Run runner:

```powershell
$env:PYTHONPATH="RpaClaw"
..\..\.venv\Scripts\python.exe -m tests.rpa_harness.run dom
```

- [ ] Step 3: Update F001 links and evidence with the Batch 2 plan and verification commands.
- [ ] Step 4: Confirm production RPA path remains untouched by Batch 2.

## Self-Review

- Spec coverage: The plan covers five DOM morphology cases, raw-vs-compact attribution, runner output, and feature evidence.
- Placeholder scan: No `TBD`, `TODO`, or unspecified acceptance gaps remain.
- Scope check: The plan excludes dashboards, production evaluators, site rule libraries, auto-promotion, multi-repair, and trace-first path changes.
- Type consistency: Case fields align with evaluator responsibilities and runner output.
