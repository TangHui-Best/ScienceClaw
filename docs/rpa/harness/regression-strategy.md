# RPA Harness Regression Strategy

## Purpose

This document explains how captured Harness assets should be used after they are
created. It should be read with [RPA Golden Evaluation Vision](golden-evaluation-vision.md),
which defines the broader golden-evaluation direction.

The strategy separates stable offline regression from live URL smoke checks.
Offline regression is the default for core-chain changes. Live URL checks are
useful, but they should not be the primary correctness oracle.

## Core Rule

Use captured HTML as the stable regression input. Use source URL as provenance,
recapture entry, and optional live smoke input.

```text
HTML asset -> deterministic offline regression
source URL -> live compatibility smoke and asset refresh
```

## Why Offline HTML Is The Main Path

Captured HTML is stable. A live URL is not:

- Page data changes.
- Login state expires.
- Enterprise permissions differ.
- A/B experiments change DOM.
- Network timing changes.
- Dynamic lists reorder.
- Backend state changes after actions.

Core RPA changes need repeatable evidence. Therefore DOM snapshot, planner, and
compiler regressions should run against captured checkpoint assets first.

## Regression Levels

### Level 0: Asset Integrity Validation

Input:

- `scenario.json`
- `steps/*/checkpoint.json`
- referenced `before.html`, `after.html`, `trace_events.json`, `expected.json`,
  and failure evidence files

Process:

1. Load every captured asset directory.
2. Validate scenario and checkpoint schema.
3. Verify that checkpoint indexes are contiguous for the captured scope.
4. Verify that Full SOP assets start at step index 1.
5. Verify that successful checkpoints have before/after HTML evidence.
6. Verify that referenced trace, expected-signal, and failure evidence files
   exist.

Questions answered:

- Is the captured asset complete enough to be used as regression evidence?
- Is a Full SOP missing its entry/navigation checkpoint?
- Would snapshot or compiler regression be testing a broken fixture?
- Can this asset be promoted from `draft` to `active` without silently
  weakening the regression set?

Typical trigger:

- After a Harness capture session.
- Before promoting an asset to `active`.
- Before running snapshot or compiler regression in CI.
- Before interpreting a snapshot/compiler failure as a code regression.

### Level 1: Snapshot Regression

Input:

- `before.html`
- `step_intent`
- capture-time raw/compact snapshots when available
- `expected.snapshot_signals`

Process:

1. Load captured HTML offline.
2. Generate current raw snapshot.
3. Generate current compact snapshot.
4. Compare current snapshots against expected signals.
5. Diff current compact snapshot against capture-time compact snapshot.

Questions answered:

- Did the target information still enter raw snapshot?
- Did compact snapshot preserve the task-critical facts?
- Did candidate/list/table/form structure survive?
- Did token size or noise grow unexpectedly?
- Did an intentional compression change affect unrelated assets?

Typical trigger:

- Changes to DOM extractor.
- Changes to `compact_recording_snapshot`.
- Changes to snapshot ranking, pruning, region grouping, candidate handling, or
  locator projection.

### Level 2: Planner/Action Selection Regression

Input:

- `before.html`
- `step_intent`
- expected action signals
- current snapshot output

Process:

1. Generate the current planner-facing page view.
2. Run the planner or a constrained planner decision check.
3. Compare selected action against expected action signals.

Questions answered:

- Can the planner still see the intended target?
- Does it select from the correct candidate/card/list context?
- Does it preserve target identity instead of inventing a weak locator?

Typical trigger:

- Changes to `RecordingRuntimeAgent`.
- Changes to planner prompt/schema.
- Changes to action-snapshot or ref/candidate contracts.

### Level 3: Trace Compiler Regression

Input:

- `trace_events.json`
- step checkpoint metadata
- expected compiler signals
- capture-time generated Skill when available

Process:

1. Compile trace events with the current `TraceSkillCompiler`.
2. Generate `skill.py` and `SKILL.md` into a temp output directory.
3. Compare output against expected compiler signals.
4. Diff against capture-time or accepted baseline output when available.

Questions answered:

- Did the compiler hard-code recording-time values?
- Did it preserve `_results` / `output_key` dataflow?
- Did it preserve semantic steps that should remain runtime AI?
- Did it generalize stable URL suffixes without freezing observed objects?
- Did it rewrite locators in a way that weakens replay?

Typical trigger:

- Changes to `TraceSkillCompiler`.
- Changes to trace models.
- Changes to recorder trace normalization.
- Changes to skill output format.

### Level 4: Offline Step Replay

Input:

- `before.html`
- trace/action facts
- expected action/state signals

Process:

1. Load captured HTML into a local Playwright page.
2. Verify that the compiled or trace-backed action target can be found.
3. Optionally execute local DOM-level interactions.
4. Compare resulting local state against limited expected state signals.

Questions answered:

- Does the action locator still match the captured DOM?
- Is target identity preserved well enough for local DOM interaction?

Limitations:

- External JS, backend calls, navigation, auth, network requests, canvas state,
  and SPA runtime behavior may not reproduce from static HTML alone.
- Offline step replay should not be treated as full business replay.

### Level 5: Live URL Smoke

Input:

- Source URL.
- Optional auth/environment fixture.
- SOP or selected-step replay instructions.

Process:

1. Open the live URL in a controlled browser context.
2. Run a small smoke subset.
3. Compare with expected high-level result.

Questions answered:

- Does the real page still resemble the captured asset?
- Has the site changed enough to require recapture?
- Does replay work in a realistic environment?

Live smoke should be:

- Manual or scheduled.
- Non-blocking by default in v0.
- Used to refresh assets, not replace offline regression.

## Change-to-Regression Matrix

| Change area | Required Harness |
| --- | --- |
| Captured asset promotion | Asset integrity validation |
| DOM extractor | Snapshot regression |
| Snapshot compression | Snapshot regression |
| Candidate/list/table/form projection | Snapshot regression + planner/action selection regression |
| Planner prompt/schema | Planner/action selection regression |
| Recording trace model | Trace compiler regression |
| Trace recorder normalization | Trace compiler regression + selected replay checks |
| `TraceSkillCompiler` | Trace compiler regression + offline step replay |
| Runtime repair policy | Failure-asset regression |
| Replay/runtime execution | Offline step replay + selected live smoke |
| RPA UI copy only | No heavy RPA Harness required |

## Regression Report

Each run should produce a report that answers:

- Which assets were tested?
- Which page pattern tags were covered?
- Which expected signals passed or failed?
- Which snapshots changed?
- Which generated Skill outputs changed?
- Which changes are high-risk but possibly intentional?
- Which assets need review, recapture, or baseline update?

Minimum report sections:

```text
Summary
Asset Coverage
Snapshot Regression
Compiler Regression
Offline Replay
Live Smoke (if any)
Failures By Category
Baseline Update Candidates
```

## Failure Categories

Use a bounded taxonomy so repeated failures become measurable:

- `missing-scenario`
- `invalid-scenario`
- `missing-checkpoint-ref`
- `invalid-checkpoint`
- `missing-entry-checkpoint`
- `step-index-gap`
- `duplicate-step-index`
- `missing-before-html`
- `missing-after-state`
- `missing-after-html`
- `missing-trace-events`
- `missing-expected-signals`
- `missing-failure-evidence`
- `unreferenced-checkpoint`
- `raw-dom-missing`
- `compact-snapshot-lost-signal`
- `candidate-context-lost`
- `label-input-relation-lost`
- `table-structure-lost`
- `locator-not-found`
- `planner-wrong-target`
- `trace-event-missing`
- `trace-dataflow-lost`
- `compiler-hardcoded-observed-value`
- `compiler-dataflow-lost`
- `offline-replay-limitation`
- `live-page-changed`
- `auth-or-permission`
- `dynamic-loading`
- `unknown`

## Baseline Updates

Not every diff is a regression. Some diffs are intentional improvements.

Recommended flow:

```text
run regression
  -> inspect diff report
  -> classify as regression or accepted change
  -> update expected signals/baseline only after review
```

Baseline updates should include a short note explaining:

- What changed.
- Why it is accepted.
- Which assets are affected.
- Whether a Scenario Note, ADR, or Lesson is needed.

## CI Strategy

v0 should avoid making every PR pay the cost of every Harness test.

Suggested tiers:

- Local required for core changes: snapshot and compiler regression on selected
  assets.
- PR subset: small active asset subset for touched core areas.
- Nightly/manual: broader regression and live smoke.

The first useful implementation can be a local CLI that writes Markdown or HTML
reports.

## Relationship To Knowledge Capture

Regression assets should feed design knowledge:

- Repeated failures in a page pattern should create or update a Scenario Note.
- Long-term architecture choices should become ADRs.
- Regressions that reveal a false assumption should become Lessons.

The asset is the evidence. The document records the reusable design knowledge
derived from that evidence.

## v0 Runner Candidates

Suggested first runner commands:

```text
python -m backend.rpa.harness.run_snapshot_regression --assets data/rpa_harness_assets
python -m backend.rpa.harness.run_compiler_regression --assets data/rpa_harness_assets
python -m backend.rpa.harness.run_catalog --assets data/rpa_harness_assets --output catalog.json
python -m backend.rpa.harness.run_blast_radius --snapshot-report snapshot.json --compiler-report compiler.json --catalog catalog.json --output blast-radius.json
```

The exact module path can change during implementation. The important boundary
is that snapshot and compiler regression are separate runners with separate
failure reports.

## v0 Catalog And Blast-Radius Reports

The catalog report is a read-only index over local assets. It is not a database,
not a live URL crawler, and not a second source of truth for scenario metadata.

Minimum catalog JSON shape:

```json
{
  "schema_version": "rpa-harness-catalog-v0",
  "summary": {
    "capture_count": 1,
    "step_count": 2,
    "successful_step_count": 1,
    "failed_step_count": 1,
    "asset_statuses": {"active": 1},
    "sensitivity": {"local-only": 1},
    "promotion_statuses": {"golden": 1},
    "runner_modes": {"offline_core_chain": 1},
    "core_chain_coverage": {
      "html_to_raw_snapshot": 1,
      "raw_to_compact_snapshot": 1,
      "trace_to_skill": 1
    },
    "recording_modes": {"natural_language": 1, "manual": 1},
    "runtime_statuses": {"success": 1, "failed": 1},
    "page_patterns": ["card-list", "detail-page"],
    "hosts": ["example.test"],
    "urls": ["https://example.test/search"]
  },
  "captures": [],
  "steps": [],
  "warnings": []
}
```

The blast-radius report is a thin aggregator over existing runner reports. It
does not rerun snapshot or compiler logic by default. It joins runner items by
`asset_id` and `step_index`, then uses the catalog only to enrich each affected
step with asset lifecycle and coverage metadata.

Minimum blast-radius JSON shape:

```json
{
  "schema_version": "rpa-harness-blast-radius-v0",
  "summary": {
    "status": "failed",
    "checked_steps": 3,
    "passed_steps": 2,
    "failed_steps": 1,
    "blocking_failed_steps": 1,
    "warning_failed_steps": 0,
    "affected_assets": ["asset-1"],
    "blocking_affected_assets": ["asset-1"],
    "warning_affected_assets": [],
    "affected_page_patterns": ["card-list"],
    "affected_hosts": ["example.test"]
  },
  "affected_steps": [],
  "failures_by_category": {"compact-snapshot-lost-signal": 1},
  "warnings": []
}
```

Exit semantics:

- `active` and unknown asset statuses are blocking by default.
- `draft`, `flaky`, `archived`, and `superseded` assets are warning evidence by
  default; they should not inflate blocking blast-radius counts.
- A step passes the combined report only when all present runner results for that
  step pass.
- Missing snapshot or compiler evidence for a checked step is reported as
  `incomplete-runner-evidence`; the CLI requires both runner reports.
