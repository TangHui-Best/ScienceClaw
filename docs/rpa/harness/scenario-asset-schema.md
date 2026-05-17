# Scenario Asset Schema

## Purpose

This document defines the v0 storage model for RPA Harness assets.

The schema centers on step checkpoints. A Harness asset may contain one step,
several selected steps, or the full SOP. The format stays the same so regression
tools can operate over assets without caring whether they came from full capture
or selected-step capture.

## Directory Layout

Suggested local layout:

```text
data/rpa_harness_assets/
  <asset_id>/
    scenario.json
    steps/
      001/
        before.html
        before.png
        before.raw_snapshot.json
        before.compact_snapshot.json
        after.html
        after.png
        after.raw_snapshot.json
        after.compact_snapshot.json
        trace_events.json
        expected.json
        failure.json
      002/
        ...
    reports/
      snapshot-regression.md
      compiler-regression.md
```

Repository-safe curated assets may later move under a dedicated test fixture
directory, but v0 assets are local by default.

## Top-Level `scenario.json`

Example:

```json
{
  "schema_version": "rpa-harness-scenario-v0",
  "asset_id": "asset-20260517-001",
  "capture_scope": "full_sop",
  "sop_intent": "Search for a project, open it, and extract repository details.",
  "source": {
    "recording_id": "rec-123",
    "captured_at": "2026-05-17T10:30:00+08:00",
    "capture_mode": "harness",
    "capture_trigger": "recording_start"
  },
  "environment": {
    "browser": "chromium",
    "viewport": {
      "width": 1440,
      "height": 900
    },
    "storage_backend": "local",
    "auth_context": "local-dev"
  },
  "asset_status": "draft",
  "sensitivity": "local-only",
  "page_patterns": ["search-result", "card-list"],
  "step_checkpoints": [
    {
      "step_index": 1,
      "checkpoint_path": "steps/001/checkpoint.json"
    }
  ]
}
```

## Top-Level Fields

| Field | Required | Notes |
| --- | --- | --- |
| `schema_version` | yes | Starts as `rpa-harness-scenario-v0`. |
| `asset_id` | yes | Stable local identifier. |
| `capture_scope` | yes | `full_sop` or `selected_steps`. |
| `sop_intent` | recommended | Overall SOP purpose when known. |
| `source.recording_id` | recommended | Links to original recording. |
| `source.captured_at` | yes | Capture timestamp. |
| `environment` | recommended | Browser, viewport, auth/storage context. |
| `asset_status` | yes | `draft`, `active`, `flaky`, `archived`, `superseded`. |
| `sensitivity` | yes | `local-only`, `sanitized`, `repo-safe`, `sensitive`. |
| `page_patterns` | recommended | High-level tags for coverage analysis. |
| `step_checkpoints` | yes | Pointers to checkpoint files. |

## Step `checkpoint.json`

Example:

```json
{
  "step_index": 2,
  "step_id": "step-002",
  "step_intent": "Click the result whose title contains ScienceClaw.",
  "recording_mode": "natural_language",
  "page_patterns": ["search-result", "card-list", "multi-candidate-selection"],
  "captured_at": "2026-05-17T10:31:12+08:00",
  "before": {
    "url": "https://example.test/search?q=scienceclaw",
    "title": "Search results",
    "html_path": "before.html",
    "html_sha256": "...",
    "screenshot_path": "before.png",
    "raw_snapshot_path": "before.raw_snapshot.json",
    "compact_snapshot_path": "before.compact_snapshot.json",
    "active_page_id": "page-main",
    "iframe_metadata": []
  },
  "action": {
    "trace_events_path": "trace_events.json",
    "expected_action_type": "click",
    "target_evidence": {
      "role": "link",
      "text_contains": "ScienceClaw",
      "container_text": ["ScienceClaw", "repository"]
    }
  },
  "after": {
    "url": "https://example.test/projects/scienceclaw",
    "title": "ScienceClaw",
    "html_path": "after.html",
    "html_sha256": "...",
    "same_as_before": false,
    "screenshot_path": "after.png",
    "raw_snapshot_path": "after.raw_snapshot.json",
    "compact_snapshot_path": "after.compact_snapshot.json"
  },
  "runtime_result": {
    "status": "success",
    "error": null
  },
  "expected_path": "expected.json"
}
```

## Required Checkpoint Fields

For a successful step:

- `step_index`
- `step_intent`
- `before.url`
- `before.title`
- `before.html_path`
- `action.trace_events_path`
- `after.url`
- `after.html_path`, or `after.same_as_before=true` with the before hash
- `runtime_result.status`
- `captured_at`

For a failed step:

- `step_index`
- `step_intent`
- `before.url`
- `before.title`
- `before.html_path`
- `runtime_result.status=failed`
- `failure.json` or equivalent error fields
- Failure-time HTML/screenshot when available

## Before/After State

The before state is the page state used for observation, planning, and action
selection. The after state is the evidence that the step succeeded, failed, or
had no side effect.

After state should exist for successful steps even when the HTML is identical.
Use hash deduplication to avoid storing duplicate files:

```json
{
  "after": {
    "same_as_before": true,
    "html_path": "before.html",
    "html_sha256": "..."
  }
}
```

## Snapshot Files

Snapshot files are derived evidence:

- `*.raw_snapshot.json`: factual browser snapshot captured at the time.
- `*.compact_snapshot.json`: planner-facing snapshot captured at the time.

The HTML remains authoritative. Regression tools should regenerate current
snapshots from HTML and compare them against both expected signals and
capture-time snapshots.

## Trace Events

`trace_events.json` should include the trace events created or accepted for the
step. It should preserve factual recording evidence, not post-hoc generalized
replay code.

Minimum useful fields:

- Action type.
- Target locator or locator candidates.
- Target text/role/label context.
- Input value or extraction result when relevant.
- Page id or tab id when available.
- Before/after URL when available.
- Output key or result reference when available.

## Expected Signals

`expected.json` turns a checkpoint into a regression test.

Example:

```json
{
  "snapshot_signals": {
    "must_contain_text": ["ScienceClaw"],
    "must_preserve_candidate_structure": true,
    "must_preserve_candidate_count_at_least": 5,
    "must_preserve_primary_action_locator": true
  },
  "action_signals": {
    "expected_action_type": "click",
    "target_role": "link",
    "target_text_contains": "ScienceClaw",
    "must_preserve_target_container_context": true
  },
  "compiler_signals": {
    "must_not_hardcode_observed_values": ["ScienceClaw"],
    "semantic_step_allowed": true
  },
  "state_signals": {
    "expected_url_change": true,
    "expected_no_side_effect": false
  }
}
```

Expected signals should be reviewed before an asset becomes `active`.

## Expected Signal Draft Sources

### Natural-Language Step

Use:

- Step intent.
- Planner result.
- Target DOM evidence.
- Trace event.
- Before/after state change.

The natural-language text should produce a structured draft, not remain the only
oracle.

### Manual Step

Use:

- Trace action type.
- Target element context.
- Locator candidates.
- Element role/name/label/placeholder.
- Container text and nearby headings.
- Before/after diff.

Manual-step expected signals must not freeze accidental selectors such as
absolute CSS paths unless no better semantic target exists.

## Page Pattern Tags

Suggested v0 tags:

- `form`
- `table`
- `grid`
- `card-list`
- `search-result`
- `detail-page`
- `modal`
- `drawer`
- `iframe`
- `multi-page`
- `pagination`
- `infinite-scroll`
- `file-upload`
- `auth-gated`
- `semantic-selection`
- `data-extraction`

Tags are metadata for coverage and filtering. They must not become runtime
site-specific rules.

## Sensitivity And Lifecycle

### Sensitivity

- `local-only`: default for freshly captured assets.
- `sanitized`: reviewed and scrubbed but not necessarily committed.
- `repo-safe`: allowed to enter version control.
- `sensitive`: retained only in a protected local location.

### Asset Status

- `draft`: captured but not reviewed.
- `active`: used by regression.
- `flaky`: useful but non-blocking.
- `archived`: retained for history only.
- `superseded`: replaced by a newer asset.

## Open Questions

v0 intentionally leaves these open:

- Whether shadow DOM serialization is needed.
- Whether iframe HTML should be captured recursively by default.
- Whether live URL smoke assets need a separate auth fixture model.
- How much expected-signal drafting should be automated before manual review.

