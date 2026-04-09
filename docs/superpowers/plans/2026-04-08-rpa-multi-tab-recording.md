# RPA Multi-Tab Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement multi-tab recording, display, and playback semantics for the RPA recorder so new tabs are auto-activated, user-switchable, and correctly replayed.

**Architecture:** Refactor the recorder manager from a single-page session model to a multi-tab session model with one active tab and a session-scoped screencast controller. Extend backend APIs and websocket payloads to expose tab state, then update generator, executor, assistant, and recorder/test pages so display and execution follow the same active tab.

**Tech Stack:** FastAPI, Playwright async API, Python unittest, Vue 3 + TypeScript

---

### Task 1: Backend session tab registry

**Files:**
- Modify: `RpaClaw/backend/rpa/manager.py`
- Create: `RpaClaw/backend/tests/test_rpa_manager.py`

- [ ] Write failing tests for tab registration, activation, and fallback on close.
- [ ] Run the manager tests to verify the multi-tab expectations fail for the current single-page implementation.
- [ ] Implement `tab_id` metadata, per-session tab registries, active-tab state, and explicit tab activation helpers in `manager.py`.
- [ ] Re-run `test_rpa_manager.py` and keep iterating until the new tests pass.

### Task 2: Session-scoped screencast and tab APIs

**Files:**
- Modify: `RpaClaw/backend/rpa/screencast.py`
- Modify: `RpaClaw/backend/route/rpa.py`
- Extend: `RpaClaw/backend/tests/test_rpa_manager.py`

- [ ] Add failing tests for tab listing payloads and active-tab screencast switching behavior using simple fakes.
- [ ] Run the targeted backend tests to confirm the current code still binds screencast to a fixed page.
- [ ] Refactor screencast handling into a session-level controller and add `GET /session/{id}/tabs` plus `POST /session/{id}/tabs/{tab_id}/activate`.
- [ ] Re-run the targeted backend tests until the controller and APIs behave consistently.

### Task 3: Generator and execution semantics

**Files:**
- Modify: `RpaClaw/backend/rpa/generator.py`
- Modify: `RpaClaw/backend/rpa/executor.py`
- Modify: `RpaClaw/backend/rpa/assistant.py`
- Modify: `RpaClaw/backend/route/rpa.py`
- Modify: `RpaClaw/backend/tests/test_rpa_generator.py`
- Extend: `RpaClaw/backend/tests/test_rpa_assistant.py`

- [ ] Add failing generator tests for `open_tab_click` and `switch_tab` output.
- [ ] Add failing assistant/executor tests covering active-page lookup instead of stale page references.
- [ ] Run the targeted tests and verify they fail for the current single-page assumptions.
- [ ] Implement `current_page`/`tabs[...]` script generation, active-tab aware execution plumbing, and active-page resolution in assistant routes.
- [ ] Re-run the targeted tests until all new playback semantics pass.

### Task 4: Recorder and test page tab strip

**Files:**
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- Modify: `RpaClaw/frontend/src/pages/rpa/TestPage.vue`

- [ ] Add frontend state for `tabs`, `activeTabId`, and tab-activation requests.
- [ ] Update the screencast websocket handlers to consume `tabs_snapshot`, `tab_created`, `tab_updated`, `tab_activated`, and `tab_closed`.
- [ ] Render a browser-like tab strip above the main canvas in both recorder and test pages.
- [ ] Verify manually that the UI remains type-safe and that tab state is isolated from the existing step/chat panes.

### Task 5: Verification

**Files:**
- Modify as needed from Tasks 1-4 only

- [ ] Run the targeted backend unit tests for manager, generator, and assistant behavior.
- [ ] Perform a focused frontend sanity pass for recorder/test page syntax and obvious runtime regressions.
- [ ] Summarize any remaining unverified gaps, especially true browser-level multi-tab flows that require manual end-to-end validation.

### Execution Notes

- Do not create any new git commits during implementation. The user will validate first and decide when to commit.
- Stay on the current working tree and branch as requested by the user.
