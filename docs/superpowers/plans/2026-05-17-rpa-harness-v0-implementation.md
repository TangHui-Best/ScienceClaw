# RPA Harness v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build RPA Harness v0 through compiler regression so RPA core-chain changes can be evaluated against captured step assets instead of page-specific guesswork.

**Architecture:** Add a config-gated Harness path that is invisible when disabled, then persist capture assets as step checkpoints. Offline regression runners consume captured HTML and trace/checkpoint assets to compare snapshot and compiler behavior without depending on live URLs.

**Tech Stack:** FastAPI/Pydantic v2 backend, Vue 3/Vite frontend, Playwright page APIs, existing RPA trace models, `TraceSkillCompiler`, pytest, Vitest.

---

## Vision Anchor

The work serves this target:

```text
Stop fixing one page bug without knowing the blast radius. Every DOM snapshot or
TraceSkillCompiler core-chain change should be testable against captured page
assets, with reports showing affected scenarios and page patterns.
```

Non-goals:

- Do not build a generic debug export product.
- Do not capture anything when `RPA_HARNESS_CAPTURE_ENABLED=false`.
- Do not replace Trace-first Recording or post-hoc `TraceSkillCompiler`.
- Do not make live URLs the primary regression oracle.
- Do not add site-specific rules as the Harness architecture.

Source design docs:

- `docs/rpa/harness/rpa-harness-v0-design.md`
- `docs/rpa/harness/scenario-asset-schema.md`
- `docs/rpa/harness/regression-strategy.md`

## Feature Sequence

Each Feature must be committed and pushed before the next Feature starts.

1. Feature 0: document and plan anchor.
2. Feature 1: zero-impact config gate and backend asset model skeleton.
3. Feature 2: capture session and Full SOP / Selected Step scope skeleton.
4. Feature 3: step before/after HTML checkpoint capture.
5. Feature 4: expected signal draft generation.
6. Feature 5: snapshot regression runner.
7. Feature 6: compiler regression runner.
8. Feature 7: real trace-first AI recording checkpoint integration.

## File Map

Likely created files:

- `RpaClaw/backend/rpa/harness/__init__.py`: package marker.
- `RpaClaw/backend/rpa/harness/models.py`: Pydantic models for assets, checkpoints, expected signals, and reports.
- `RpaClaw/backend/rpa/harness/config.py`: gate helpers and asset directory resolution.
- `RpaClaw/backend/rpa/harness/store.py`: local asset writer/reader.
- `RpaClaw/backend/rpa/harness/capture.py`: capture session/checkpoint orchestration.
- `RpaClaw/backend/rpa/harness/expected_signals.py`: expected-signal draft helpers.
- `RpaClaw/backend/rpa/harness/snapshot_regression.py`: offline snapshot regression logic.
- `RpaClaw/backend/rpa/harness/compiler_regression.py`: trace compiler regression logic.
- `RpaClaw/backend/rpa/harness/run_snapshot_regression.py`: CLI entrypoint.
- `RpaClaw/backend/rpa/harness/run_compiler_regression.py`: CLI entrypoint.
- `RpaClaw/backend/tests/test_rpa_harness_*.py`: focused backend tests.
- `RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py`: real natural-language recording capture integration tests.

Likely modified files:

- `RpaClaw/backend/config.py`: add `RPA_HARNESS_CAPTURE_ENABLED` and asset dir settings.
- `RpaClaw/backend/rpa/manager.py`: attach capture state only when enabled and requested.
- `RpaClaw/backend/route/rpa.py`: expose config-gated capture metadata and capture controls.
- `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`: show capture controls only when backend says enabled.
- `RpaClaw/frontend/src/locales/en.ts` and `RpaClaw/frontend/src/locales/zh.ts`: UI strings when UI work starts.
- `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`: UI gate tests when UI work starts.

## Feature 0: Document And Plan Anchor

**Files:**

- Create: `docs/rpa/harness/rpa-harness-v0-design.md`
- Create: `docs/rpa/harness/scenario-asset-schema.md`
- Create: `docs/rpa/harness/regression-strategy.md`
- Create: `docs/superpowers/plans/2026-05-17-rpa-harness-v0-implementation.md`

- [ ] **Step 1: Inspect docs**

Run:

```powershell
rg -n "RPA_HARNESS_CAPTURE_ENABLED|Full SOP|Selected Step|Step Checkpoint|HTML Is The Source Of Truth|diagnostic|Page Capture" docs\rpa\harness docs\superpowers\plans\2026-05-17-rpa-harness-v0-implementation.md
```

Expected:

- Finds the intended terms.
- Does not find `diagnostic` as a capture mode.
- Does not find standalone `Page Capture` as a v0 mode.

- [ ] **Step 2: Commit and push**

Run:

```powershell
git add docs\rpa\harness docs\superpowers\plans\2026-05-17-rpa-harness-v0-implementation.md
git commit -m "docs: define rpa harness v0"
git push -u origin codex/rpa-trace-first-harness
```

Expected: commit and push succeed.

## Feature 1: Zero-Impact Gate And Asset Models

**Files:**

- Modify: `RpaClaw/backend/config.py`
- Create: `RpaClaw/backend/rpa/harness/__init__.py`
- Create: `RpaClaw/backend/rpa/harness/config.py`
- Create: `RpaClaw/backend/rpa/harness/models.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_config.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_models.py`

- [ ] **Step 1: Write failing config tests**

Test behaviors:

- Missing `RPA_HARNESS_CAPTURE_ENABLED` means disabled.
- False-like values are disabled.
- True-like values are enabled.
- Default asset directory derives from `settings.local_data_dir`.

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_config.py -q
```

Expected: fails because harness config module does not exist yet.

- [ ] **Step 2: Implement minimal gate config**

Add settings fields:

```python
rpa_harness_capture_enabled: bool = os.environ.get("RPA_HARNESS_CAPTURE_ENABLED", "false").lower() == "true"
rpa_harness_assets_dir: str = _sub("RPA_HARNESS_ASSETS_DIR", _resolve_home(), "rpa_harness_assets", "./data/rpa_harness_assets")
```

Add helper functions that read these settings without creating files or sessions.

- [ ] **Step 3: Write failing model tests**

Test behaviors:

- Asset model supports `capture_scope="full_sop"` and `capture_scope="selected_steps"`.
- Checkpoint requires `step_intent`, before state, action state, runtime result.
- After state can reference before with `same_as_before=true`.
- Sensitivity defaults to `local-only`, status defaults to `draft`.

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_models.py -q
```

Expected: fails until models exist.

- [ ] **Step 4: Implement Pydantic models**

Create stable Pydantic v2 models matching `docs/rpa/harness/scenario-asset-schema.md`. Do not import Playwright or mutate recording sessions.

- [ ] **Step 5: Verify Feature 1**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_config.py RpaClaw/backend/tests/test_rpa_harness_models.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit and push**

Run:

```powershell
git add RpaClaw/backend/config.py RpaClaw/backend/rpa/harness RpaClaw/backend/tests/test_rpa_harness_config.py RpaClaw/backend/tests/test_rpa_harness_models.py
git commit -m "feat: add rpa harness asset gate and models"
git push
```

## Feature 2: Capture Session Skeleton

**Files:**

- Modify: `RpaClaw/backend/rpa/harness/capture.py`
- Modify: `RpaClaw/backend/rpa/manager.py`
- Modify: `RpaClaw/backend/route/rpa.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_capture_session.py`

- [ ] **Step 1: Write failing tests**

Test behaviors:

- When the gate is disabled, starting an RPA session does not attach capture state.
- When enabled and requested, a capture session records `capture_scope`.
- Selected-step marking stores selected indexes without capturing HTML yet.
- Full SOP scope records intent to capture all steps but does not change normal traces.

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_capture_session.py -q
```

Expected: fails because capture session logic is absent.

- [ ] **Step 2: Implement capture session skeleton**

Add an in-memory capture session manager that can be attached to an RPA session
only when enabled and requested. The skeleton should not call `page.content()`.

- [ ] **Step 3: Add route surface**

Add config-gated route support for capture metadata/control. Default response
must remain compatible and not expose capture controls when disabled.

- [ ] **Step 4: Verify Feature 2**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_capture_session.py RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_route_trace.py -q
```

- [ ] **Step 5: Commit and push**

```powershell
git add RpaClaw/backend/rpa/harness RpaClaw/backend/rpa/manager.py RpaClaw/backend/route/rpa.py RpaClaw/backend/tests/test_rpa_harness_capture_session.py
git commit -m "feat: add rpa harness capture session skeleton"
git push
```

## Feature 3: Step HTML Checkpoint Capture

**Files:**

- Modify: `RpaClaw/backend/rpa/harness/capture.py`
- Modify: `RpaClaw/backend/rpa/harness/store.py`
- Modify: `RpaClaw/backend/rpa/manager.py`
- Modify: `RpaClaw/backend/route/rpa.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py`

- [ ] **Step 1: Write failing tests**

Use fake page objects for:

- `url`
- `title()`
- `content()`
- optional `screenshot()`

Test behaviors:

- Successful selected step writes before and after HTML.
- Identical after HTML is hash-deduplicated with `same_as_before=true`.
- Failed step records before state and failure evidence.
- Checkpoint records `step_intent`.

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py -q
```

- [ ] **Step 2: Implement local store**

Write files under the configured asset dir. Use JSON with `model_dump(mode="json")`. Never write outside the resolved asset root.

- [ ] **Step 3: Integrate checkpoint hooks**

Capture before/after around selected steps and full-SOP steps. Keep all capture paths behind the gate and active capture session checks.

- [ ] **Step 4: Verify Feature 3**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_capture_session.py -q
```

- [ ] **Step 5: Commit and push**

```powershell
git add RpaClaw/backend/rpa/harness RpaClaw/backend/rpa/manager.py RpaClaw/backend/route/rpa.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py
git commit -m "feat: capture rpa harness step checkpoints"
git push
```

## Feature 4: Expected Signal Drafts

**Files:**

- Create: `RpaClaw/backend/rpa/harness/expected_signals.py`
- Modify: `RpaClaw/backend/rpa/harness/capture.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_expected_signals.py`

- [ ] **Step 1: Write failing tests**

Test natural-language step:

- Intent containing a click target creates action and snapshot signal draft.

Test manual step:

- Trace/target context creates role/name/label/container-based signals.
- Absolute CSS selector is not the main expected signal when semantic evidence exists.

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_expected_signals.py -q
```

- [ ] **Step 2: Implement draft generation**

Generate conservative drafts only. Do not invent site-specific classifications.

- [ ] **Step 3: Attach drafts to checkpoints**

Write `expected.json` with draft signals when capture data is available.

- [ ] **Step 4: Verify Feature 4**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py -q
```

- [ ] **Step 5: Commit and push**

```powershell
git add RpaClaw/backend/rpa/harness RpaClaw/backend/tests/test_rpa_harness_expected_signals.py
git commit -m "feat: draft expected signals for harness checkpoints"
git push
```

## Feature 5: Snapshot Regression Runner

**Files:**

- Create: `RpaClaw/backend/rpa/harness/snapshot_regression.py`
- Create: `RpaClaw/backend/rpa/harness/run_snapshot_regression.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py`

- [ ] **Step 1: Write failing tests**

Test behaviors:

- Runner loads checkpoint HTML from an asset directory.
- Runner calls snapshot builder/compressor through injectable functions.
- Report marks missing expected text as failure.
- Report includes asset id, step id, page patterns, and failure category.

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py -q
```

- [ ] **Step 2: Implement regression logic**

Keep runner offline and injectable. Do not require live browser for unit tests.

- [ ] **Step 3: Add CLI entrypoint**

Support:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m backend.rpa.harness.run_snapshot_regression --assets data/rpa_harness_assets
```

- [ ] **Step 4: Verify Feature 5**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_expected_signals.py -q
```

- [ ] **Step 5: Commit and push**

```powershell
git add RpaClaw/backend/rpa/harness RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py
git commit -m "feat: add rpa harness snapshot regression"
git push
```

## Feature 6: Compiler Regression Runner

**Files:**

- Create: `RpaClaw/backend/rpa/harness/compiler_regression.py`
- Create: `RpaClaw/backend/rpa/harness/run_compiler_regression.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py`

- [ ] **Step 1: Write failing tests**

Test behaviors:

- Runner loads trace events from checkpoint assets.
- Runner invokes an injectable compiler.
- Report flags hard-coded observed values listed in expected compiler signals.
- Report flags missing dataflow/output references when expected.
- Report includes generated script diff summary when a baseline exists.

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py -q
```

- [ ] **Step 2: Implement compiler regression logic**

Use `TraceSkillCompiler` by default but keep tests injectable.

- [ ] **Step 3: Add CLI entrypoint**

Support:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m backend.rpa.harness.run_compiler_regression --assets data/rpa_harness_assets
```

- [ ] **Step 4: Verify Feature 6**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q
```

- [ ] **Step 5: Commit and push**

```powershell
git add RpaClaw/backend/rpa/harness RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py
git commit -m "feat: add rpa harness compiler regression"
git push
```

## Feature 7: Real AI Recording Checkpoint Integration

**Files:**

- Modify: `RpaClaw/backend/route/rpa.py`
- Modify: `RpaClaw/backend/rpa/manager.py`
- Modify: `RpaClaw/backend/rpa/harness/capture.py`
- Modify: `RpaClaw/backend/rpa/harness/expected_signals.py`
- Test: `RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py`

- [x] **Step 1: Integrate pre-action capture into the trace-first AI branch**

Capture the before page state before `RecordingRuntimeAgent.run()` mutates the page.
Only wire the real natural-language trace-first branch; do not wire legacy chat/react
or manual browser-event paths in this Feature.

- [x] **Step 2: Preserve disabled-path zero impact**

When `RPA_HARNESS_CAPTURE_ENABLED=false` or there is no active capture session,
the route must not call `page.content()`, construct asset stores, or write files.
This must also hold if an old in-memory capture session exists after the config is
turned off.

- [x] **Step 3: Persist accepted-trace evidence**

Use the accepted `RPAAcceptedTrace` result as the trace event source. Expected-signal
drafting must read semantic target evidence from accepted trace signals, including
`signals.target_evidence`.

- [x] **Step 4: Verify Feature 7**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py RpaClaw/backend/tests/test_rpa_route_trace.py -q --basetemp .pytest-harness-tmp
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_harness_config.py RpaClaw/backend/tests/test_rpa_harness_models.py RpaClaw/backend/tests/test_rpa_harness_capture_session.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py -q --basetemp .pytest-harness-tmp
```

- [ ] **Step 5: Commit and push**

```powershell
git add docs/superpowers/plans/2026-05-17-rpa-harness-v0-implementation.md RpaClaw/backend/route/rpa.py RpaClaw/backend/rpa/manager.py RpaClaw/backend/rpa/harness/capture.py RpaClaw/backend/rpa/harness/expected_signals.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py
git commit -m "feat: capture ai recording steps as harness assets"
git push
```

## Vision Guardian Checkpoints

An independent Vision Guardian must review:

- After Feature 0: plan still targets asset-backed impact analysis.
- After Feature 3: capture is step-checkpoint asset capture, not generic diagnostics.
- After Feature 6: regression runners can answer blast-radius questions over assets.
- After Feature 7: real AI recording capture still has zero disabled-path impact and records semantic expected signals from accepted trace evidence.

## Closeout Checklist For Each Feature

Before each commit:

- Re-read the Feature acceptance criteria.
- Run the Feature verification command.
- Confirm `git diff --stat` only contains intended files.
- Use a change narrative for the commit message.
- Commit only that Feature's files.
- Push before starting the next Feature.
