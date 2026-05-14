# RPA Trace Multi-tab Parity Design

## Status

Implemented in compiler and trace-recorder unit coverage on 2026-05-12.

## Source Context

- User report: recording used two browser tabs for different websites, but generated replay script opened both URLs in the same tab.
- Current generated script shape: `current_page = page`, `tabs = {}`, then two consecutive `current_page.goto(...)` calls.
- Related design anchors:
  - `docs/superpowers/specs/2026-04-08-rpa-multi-tab-recording-design.md`
  - `docs/superpowers/specs/2026-04-20-rpa-trace-first-recording-design.md`
  - `docs/superpowers/specs/2026-04-28-rpa-trace-first-full-migration-design.md`

## Problem

The multi-tab design was originally implemented in the step/generator path, but the current trace-first compile path does not fully preserve or consume tab topology.

The bug is not that Playwright cannot replay multiple tabs. The bug is that the accepted trace timeline given to `TraceSkillCompiler` may contain only linear navigation facts:

```text
navigate tab A to URL 1
press Enter
navigate tab B to URL 2
```

If the second navigation's tab identity is missing or ignored, the compiler can only emit:

```python
await current_page.goto(url_1)
await current_page.goto(url_2)
```

That loses the user's recorded browser topology.

## Vision Anchor

RPA recording must preserve browser tab topology as factual trace evidence, and replay must consume that evidence deterministically. The system must not infer new tabs from URL differences, because same-tab cross-site navigation is a valid user action.

## Goals

- Preserve `tab_id`, `source_tab_id`, `target_tab_id`, and popup/open-tab facts from recording into accepted traces.
- Make `TraceSkillCompiler` replay trace-backed tab topology with `tabs` and `current_page`.
- Keep same-tab consecutive navigation unchanged.
- Treat missing tab facts as diagnostics or conservative same-tab replay, not as URL-based guessing.
- Restore parity with the older `PlaywrightGenerator` multi-tab behavior where that behavior is backed by recorded tab facts.

## Non-goals

- Do not introduce a contract-first recording layer.
- Do not use URL domain changes as proof of a new tab.
- Do not add site-specific rules for GitHub, BrowserAct, or any other website.
- Do not redesign frontend tab UI.
- Do not remove `PlaywrightGenerator` in this fix.

## Design

### 1. Recording Fact Boundary

Browser chrome actions such as opening a new tab or switching tabs cannot be reliably captured by page-injected JavaScript alone. The authoritative sources for tab topology are Playwright context/page events and session manager state:

- `context.on("page")`
- `page.on("framenavigated")`
- `activate_tab(...)`
- `register_context_page(...)`
- `close_tab(...)`

When a new page appears:

- If it follows a recent click or press on the opener tab, attach a `popup` signal to that action with `source_tab_id` and `target_tab_id`.
- If it does not follow a page action, record a system/manual tab fact so later navigation on the new tab has a known `tab_id`.
- Every navigation event must carry the `tab_id` of the page that navigated.

### 2. Trace Metadata Preservation

The step-to-trace compatibility layer must preserve tab facts into `RPAAcceptedTrace.signals["tab"]`.

Required tab signal fields:

```json
{
  "tab_id": "current-tab",
  "source_tab_id": "previous-tab",
  "target_tab_id": "next-tab",
  "opener_tab_id": "opener-tab"
}
```

Only fields that are actually known should be written. Unknown fields must not be invented.

### 3. Compiler Consumption

`TraceSkillCompiler` should initialize the tab registry from the first trace that has a tab id:

```python
tabs = {"<root_tab_id>": page}
current_page = page
```

Before rendering each trace, the compiler should align `current_page` with that trace's tab fact:

- Known tab id: switch to `tabs[tab_id]`.
- Unknown new tab id carried by a trace: create `await current_page.context.new_page()` and store it in `tabs[tab_id]`. This is allowed because the `tab_id` is recorded topology evidence, not a URL-based guess.
- Popup signal on click/press: use `expect_popup()`, store the popup page under `target_tab_id`, and make it current.
- No tab fact: keep existing `current_page` behavior.

Navigation rendering remains `current_page.goto(...)`, but now `current_page` is the page selected by factual tab metadata.

### 4. Conservative Missing-data Policy

If a navigation trace appears to belong to an unknown tab but no explicit open-tab or popup fact exists, the compiler should not guess from URL shape.

Acceptable short-term behavior:

- Materialize a new page only when the trace itself carries a factual `tab_id`.
- Emit a compile-time comment explaining that opener/popup evidence was missing.
- Do not emit a new formal `RPATraceDiagnostic` in the first fix; this avoids expanding the diagnostics contract before the trace-native migration is complete.

Preferred behavior after recording fixes:

- The missing-data branch should be rare and covered by a regression test.

## Acceptance Criteria

1. A trace sequence with two navigation traces on the same `tab_id` compiles to same-tab navigation.
2. A trace sequence where the second navigation carries a different, known tab fact compiles to a separate page before navigating.
3. A click/press trace with `signals.popup.target_tab_id` compiles with `expect_popup()` and subsequent traces on that tab run on the popup page.
4. A switch-tab trace compiles to `current_page = tabs[target_tab_id]`.
5. The compiler does not create a new tab solely because two consecutive navigation URLs have different domains.
6. Recording manager tests prove navigation events carry the page's actual `tab_id`.
7. Route/session compile tests prove `_session_traces_for_compile(...)` does not drop tab signals when merging step, recorded action, and trace data.

## Test Plan

Backend unit tests:

- `test_rpa_trace_skill_compiler.py`
  - same-tab consecutive navigation stays same-page
  - known new-tab navigation materializes/switches page before `goto`
  - popup click preserves `expect_popup()` and target tab
  - missing tab fact does not use URL-difference inference
- `test_rpa_trace_recorder.py`
  - manual navigation step preserves `signals.tab.tab_id`
  - recorded/manual conversion preserves tab metadata where available
- `test_rpa_manager.py`
  - `framenavigated` events include the registered tab id
  - `register_context_page(...)` attaches popup facts only when a recent opener action exists
- `test_rpa_route_trace.py`
  - compile session with traces/recorded actions/steps preserves tab signals into generated script

Verification:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_recorder.py RpaClaw/backend/tests/test_rpa_route_trace.py RpaClaw/backend/tests/test_rpa_manager.py
```

## Implementation Evidence

Implemented changes:

- `TraceSkillCompiler` initializes `tabs` from recorded trace tab facts.
- `TraceSkillCompiler` materializes a new Playwright page when a later trace carries a new factual `tab_id`.
- Same-tab consecutive navigation remains same-page.
- URL differences without tab facts do not create a new tab.
- `manual_step_to_trace(...)` coverage confirms navigation steps preserve `signals.tab.tab_id`.
- Replay preview switching is now explicit: generated scripts call `_activate_recorded_page(...)` after materializing, switching to, or receiving a popup tab; `ScriptExecutor` injects that hook only when a session manager is available.
- `RPASessionManager.register_page(...)` is idempotent for the same Playwright `Page`, preventing duplicate tab metadata when both the explicit hook and `context.on("page")` observe the same page.
- Route-level coverage was added for trace navigation tab ids, but local execution is currently blocked by missing `langchain_core` during `test_rpa_route_trace.py` collection.

Fresh verification run:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_executor.py RpaClaw/backend/tests/test_rpa_manager.py
```

Result:

```text
153 passed
```

Earlier compiler/recorder verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_recorder.py
```

Result:

```text
69 passed
```

Blocked verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest RpaClaw/backend/tests/test_rpa_route_trace.py -k "preserves_trace_tab_ids_for_navigation_pages"
```

Result:

```text
ModuleNotFoundError: No module named 'langchain_core'
```

Harness check note:

- No `scripts/knowledge_check.py` or Harness templates were present in this workspace, so no knowledge-check script was run for this document.

## Rollback

The change should be isolated to trace metadata preservation and `TraceSkillCompiler` tab consumption. If regression appears, revert the compiler tab-alignment changes while retaining tests that document the missing behavior.

## Decisions

1. The compiler may materialize an unknown tab when the trace carries an explicit `tab_id`. The `tab_id` is factual topology evidence; URL differences are not.
2. Missing opener/popup evidence should be represented as a generated script comment in this fix, not as a new formal diagnostic contract.

## Recommendation

Use explicit recorded tab facts as the only source of replay tab topology. Implement compiler parity for factual `tab_id` changes and popup signals, and harden the recording/merge path so those facts are not lost before compilation.
