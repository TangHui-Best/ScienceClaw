# RPA Harness v0 Design

## Purpose

RPA Harness is the engineering layer for making the RPA Agent's core chain
observable, reproducible, and regression-testable.

It is different from the local AI-development Harness skills used to govern how
agents edit this repository. This document is about the product/runtime Harness
for the RPA system itself:

```text
SOP intent -> recording step -> page state -> DOM/HTML evidence
  -> raw/compact snapshot -> trace -> Skill compilation -> replay
```

The v0 goal is not to build a large platform. The goal is to turn selected real
recording steps into durable assets that can later verify risky changes in DOM
snapshot compression, trace recording, and `TraceSkillCompiler`.

## Problem

The current RPA project has repeated failures where a fix for one page or DOM
shape may affect another page shape. The most dangerous fixes often touch shared
core layers:

- DOM extraction and snapshot compression.
- Planner-facing compact snapshot shape.
- Trace event normalization.
- Trace-to-Skill compilation and generalization.
- Replay behavior and dataflow.

Without Harness assets, the team cannot reliably answer:

- Which real page shapes have already been encountered?
- Which HTML/DOM structures drove prior design choices?
- Did a snapshot compression change remove task-critical evidence?
- Did a compiler change hard-code recording-time values or break dataflow?
- Did a fix improve one page while regressing another?

## Core Principles

### HTML Is The Source Of Truth

Captured HTML is the durable raw asset. URL is still recorded, but URL is not a
stable regression oracle because live pages, data, auth state, A/B tests, and
network behavior change.

The captured HTML should be used as the primary offline regression input for
snapshot, planner, and compiler analysis.

### Step Checkpoint Is The Unified Model

Harness assets are built from step checkpoints. A full SOP capture is a list of
all step checkpoints. A selected-step capture is a list of only marked step
checkpoints.

There is no separate page-capture asset type in v0. Single-page or single-step
analysis is represented by a one-step checkpoint asset.

### Capture Must Be Explicit

`RPA_HARNESS_CAPTURE_ENABLED=false` must preserve the existing user-visible and
runtime behavior exactly:

- No Harness UI entry.
- No capture session.
- No extra HTML capture.
- No extra screenshots.
- No extra snapshot generation.
- No trace behavior changes.
- No storage overhead.
- No timing or execution-path changes.

When enabled, Harness capture is still opt-in per recording session or per
selected step. Capture is a recording mode, not an after-the-fact attempt to
recover lost page state.

### Snapshot Is Evidence, Not The Original Asset

`raw_snapshot` and `compact_snapshot` can be regenerated from HTML, but the
capture-time snapshots should still be stored when available. They show what the
system actually saw at recording time and become the baseline for later diff
reports.

```text
captured HTML = original page fact
captured snapshot = recording-time system view
current snapshot = current-code system view
diff report = regression evidence
```

### Expected Signals Turn Assets Into Tests

HTML alone is only an archive. A Harness asset becomes a test when it also has
expected signals derived from step intent, trace facts, target DOM context, or
manual review.

Expected signals should describe stable semantics, not brittle selectors or
site-specific rules.

## Capture Scope

### Full SOP Capture

Captures every step checkpoint in a recording.

Use this when the value is in the whole SOP chain:

- Cross-step dataflow.
- Multi-page navigation.
- Trace-to-Skill compilation.
- Replay of a full generated Skill.
- Generalization across dynamic values.

### Selected Step Capture

Captures only steps explicitly marked during recording.

Use this when only specific high-risk steps need durable assets:

- A complex table, grid, list, card, form, or modal step.
- A step that exposed a snapshot compression failure.
- A step whose trace event is difficult to compile.
- A step that should become a focused regression case without replaying the
  whole SOP.

Selected step capture uses the same checkpoint schema as full SOP capture.

## Step Checkpoint Lifecycle

For a successful step, Harness should capture before and after state:

```text
before page state + step intent + action/trace evidence -> after page state
```

The after state should be recorded even when the page appears unchanged. Many
steps change values, focus, hidden fields, validation state, or internal DOM
state without visible navigation. To reduce storage, the implementation may
deduplicate identical HTML by hash:

```json
{
  "after": {
    "same_as_before": true,
    "html_sha256": "..."
  }
}
```

For a failed step, Harness should at least capture:

- Before state.
- Step intent.
- Failure-time evidence if available.
- Error category/message/stack.
- Trace or attempted action facts.

## Minimum v0 Capture Contents

Required for each step checkpoint:

- `step_index`
- `step_intent`
- `before.url`
- `before.title`
- `before.html`
- `action.trace_events`
- `after.url` and `after.html` for successful steps
- `runtime_result`
- `captured_at`

Recommended:

- Before/after screenshot.
- Before/after raw snapshot.
- Before/after compact snapshot.
- Active page metadata and page id.
- Iframe metadata.
- Target element context.
- Expected signal draft.
- Failure category.
- Page pattern tags.

## HTML Capture Scope

v0 should use:

```text
Playwright page.content()
```

plus lightweight metadata:

- URL.
- Title.
- Viewport.
- Active page id.
- Known pages in the browser context when practical.
- Iframe metadata when available.

This is intentionally smaller than a full browser archive. CSS, JS, network
responses, images, shadow DOM serialization, and full resource snapshots are
not required for v0 unless a later Harness case proves they are needed.

## Expected Signals

Expected signals may come from two recording modes.

### Natural-Language Recording Step

The user instruction is the step intent. It should be converted into a structured
expected-signal draft. Example:

```text
Click the search result whose title contains ScienceClaw.
```

Expected signal draft:

```json
{
  "snapshot_signals": {
    "must_contain_text": ["ScienceClaw"],
    "must_preserve_candidate_structure": true,
    "must_preserve_primary_action_locator": true
  },
  "action_signals": {
    "expected_action_type": "click",
    "target_text_contains": "ScienceClaw"
  }
}
```

The natural-language instruction is not stored as the only oracle. It is the
source for a structured draft that can be reviewed and refined.

### Manual Recording Step

Manual operations do not always have a natural-language intent. They can still
produce stable expected signals from trace facts and target DOM context:

- Action type.
- Target role/name/label/placeholder.
- Target container text.
- Target locator candidates.
- Before/after state change.
- Input value policy.

The expected signal should not freeze an accidental CSS selector or observed
runtime value. It should express the stable browser fact the step depended on.

Example:

```json
{
  "action_signals": {
    "expected_action_type": "fill",
    "target_role": "textbox",
    "target_label_or_placeholder": "Project name"
  },
  "snapshot_signals": {
    "must_preserve_label_input_relation": true
  },
  "compiler_signals": {
    "input_value_policy": "parameterize"
  }
}
```

## Asset Safety

Assets are local by default. Moving an asset into the repository requires manual
review of sensitivity.

Every asset should carry a sensitivity marker:

- `local-only`
- `sanitized`
- `repo-safe`
- `sensitive`

HTML and screenshots may contain private customer data, internal application
structure, user input, or business workflow details. Harness capture should not
silently upload or commit assets.

## Non-goals

v0 does not attempt to:

- Add a heavy contract-first layer to recording.
- Replace Trace-first Recording.
- Replace post-hoc `TraceSkillCompiler`.
- Build a full dashboard.
- Run all live URL replay in CI.
- Capture every ordinary recording by default.
- Treat site-specific DOM rules as architecture.

## Relationship To Existing RPA Direction

This design supports the current project direction:

```text
Trace-first Recording + Post-hoc Skill Compilation
```

Harness capture preserves factual page and trace evidence so that future changes
to snapshot compression and compilation can be tested against real captured page
states.

Related existing documents:

- [Snapshot Candidate Collection Analysis](../snapshot-candidate-collection-analysis.md)
- [TraceSkillCompiler Generalization Strategy](../trace-skill-compiler-generalization.md)
- [Snapshot Evidence Store Experiment](../experiments/2026-04-snapshot-evidence-store.md)
- [ScienceClaw vs OpenClaw Browser Contract Comparison](../openclaw-browser-contract-comparison.md)

## Recommended v0 Milestone

The first implementation milestone should be:

```text
RPA Harness v0: Scenario Asset + Step Checkpoint Capture + Snapshot/Compiler Regression
```

Scope:

1. Add a config-gated Harness capture entry.
2. Add full SOP and selected-step capture scopes.
3. Persist step checkpoint assets locally.
4. Generate expected signal drafts.
5. Implement snapshot regression over captured HTML.
6. Implement compiler regression over captured trace/checkpoint assets.
7. Produce a local Markdown or HTML report.

