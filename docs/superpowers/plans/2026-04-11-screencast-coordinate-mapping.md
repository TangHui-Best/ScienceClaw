# Screencast Coordinate Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local screencast input map exactly to the visible browser viewport across resolutions, DPI scales, and resized windows.

**Architecture:** Backend exposes viewport CSS-pixel input metrics from CDP and dispatches those coordinates directly. Frontend computes contain-fit geometry once in a shared utility and uses it to map DOM pointer positions into viewport CSS pixels for every local screencast canvas.

**Tech Stack:** FastAPI, Playwright CDP, Vue 3, TypeScript, unittest, Vitest

---

### Task 1: Backend Regression Coverage

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_screencast.py`
- Test: `RpaClaw/backend/tests/test_rpa_screencast.py`

- [ ] **Step 1: Write failing tests for viewport metric selection and mouse dispatch**

- [ ] **Step 2: Run `pytest RpaClaw/backend/tests/test_rpa_screencast.py -q` and confirm the new assertions fail for the current implementation**

- [ ] **Step 3: Keep tests focused on CSS viewport dimensions instead of screen-sized metadata**

- [ ] **Step 4: Re-run `pytest RpaClaw/backend/tests/test_rpa_screencast.py -q` after implementation**

### Task 2: Frontend Geometry Coverage

**Files:**
- Create: `RpaClaw/frontend/src/utils/screencastGeometry.ts`
- Create: `RpaClaw/frontend/src/utils/screencastGeometry.test.ts`

- [ ] **Step 1: Write failing tests for contain-fit mapping with exact fit, horizontal bars, vertical bars, and resize-sensitive cases**

- [ ] **Step 2: Run `npm test` equivalent for the new frontend unit target once test tooling is added or available**

- [ ] **Step 3: Implement pure geometry helpers only after the tests fail for the expected reasons**

- [ ] **Step 4: Re-run the frontend unit target and confirm it passes**

### Task 3: Shared Frontend Mapping Adoption

**Files:**
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- Modify: `RpaClaw/frontend/src/pages/rpa/TestPage.vue`
- Modify: `RpaClaw/frontend/src/components/SandboxPreview.vue`
- Modify: `RpaClaw/frontend/src/components/toolViews/BrowserToolView.vue`
- Modify: `RpaClaw/frontend/package.json`

- [ ] **Step 1: Add or wire frontend test tooling only as needed for the new utility tests**

- [ ] **Step 2: Replace per-component ad hoc frame sizing logic with the shared screencast geometry helpers**

- [ ] **Step 3: Ensure interactive canvases send viewport CSS-pixel coordinates and non-interactive previews still render correctly**

- [ ] **Step 4: Run the new frontend tests and `npm run type-check`**

### Task 4: Backend CSS-Pixel Dispatch

**Files:**
- Modify: `RpaClaw/backend/rpa/screencast.py`

- [ ] **Step 1: Fetch and cache `Page.getLayoutMetrics().cssVisualViewport.clientWidth/clientHeight`**

- [ ] **Step 2: Send both frame bitmap dimensions and viewport input dimensions in screencast frame payloads**

- [ ] **Step 3: Update mouse and wheel dispatch to consume CSS-pixel coordinates directly**

- [ ] **Step 4: Re-run backend screencast tests**

### Task 5: Final Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-04-11-screencast-coordinate-mapping-design.md`
- Modify: `docs/superpowers/plans/2026-04-11-screencast-coordinate-mapping.md`

- [ ] **Step 1: Run `pytest RpaClaw/backend/tests/test_rpa_screencast.py -q`**

- [ ] **Step 2: Run the frontend unit command for `screencastGeometry.test.ts`**

- [ ] **Step 3: Run `npm run type-check` in `RpaClaw/frontend`**

- [ ] **Step 4: Update docs only if implementation details changed materially**
