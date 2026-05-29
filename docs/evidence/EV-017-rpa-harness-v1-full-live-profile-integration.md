---
id: EV-017
doc_kind: evidence
title: RPA Harness v1 Full/Live Profile Integration Evidence
status: active
scope: project
feature_ids: [F017]
feature_refs:
  - docs/features/F017-rpa-harness-v1-full-live-profile-integration.md
created: 2026-05-28
updated: 2026-05-28
evidence_level: exhaustive
---

# EV-017 RPA Harness v1 Full/Live Profile Integration Evidence

## Scope

Evidence for F017: implement RPA Harness v1 Phase 5 first slice, Full/Live Profile
Integration.

This slice integrates F012 live-agent execution with the v1 profile/report model:

```text
governed asset natural-language input event
  -> controlled fixture from captured before.html and checkpoint facts
  -> RecordingRuntimeAgent.run()
  -> generated candidate-lite/profile artifact
  -> post-capture validation / snapshot / compiler / skill replay / stateful SOP
  -> JSON-first full-live profile report + Markdown summary
```

The slice must preserve:

```text
Scripts execute.
Agents explain.
Humans govern.
```

Phase 5 first slice does not add CI blocking, live URL oracle, direct outer-Agent UI
operation, automatic diagnosis, automatic candidate/golden promotion, or
region-specific runner architecture.

## Entry Gate

Start Gate:

```text
Start Gate: needs retrieval -> satisfied; needs vision gate -> satisfied;
needs feature/plan -> satisfied by F017 and Phase 5 plan before implementation
Task class: high-risk
Risk triggers:
- live Planner/LLM execution path
- Harness profile/report contract
- generated asset governance and candidate-lite boundary
- controlled fixture safety
- possible drift toward live URL oracle, direct Agent UI operation, automatic diagnosis,
  automatic promotion, or region-specific architecture
Delegation decision:
- authorized for read-only sidecar exploration because the user explicitly allowed
  subagents for complex tasks
Bug attribution:
- not triggered; this is a new Phase 5 Feature slice
Required pre-work:
- retrieve F012/F016/v1 design/ADR-003/usage guide and relevant runner code
- create F017/EV-017 and Phase 5 plan before code
Allowed next action:
- write RED tests for full-live profile report contract, CLI dispatch,
  fake-planner invocation, generated asset isolation, no-input failure,
  post-capture summary, and region_context pass-through
```

Knowledge Retrieval:

- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/rpa/harness/RPA-Harness-v1-设计.md`.
- Read `docs/features/F016-rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/features/F012-live-agent-eval-for-rpa-harness.md`.
- Read `docs/evidence/EV-012-live-agent-eval-for-rpa-harness.md`.
- Read `docs/rpa/harness/live-agent-eval.md`.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.
- Read `RpaClaw/backend/rpa/harness/profile_runner.py`.
- Read `RpaClaw/backend/rpa/harness/user_input_replay.py`.
- Read `RpaClaw/backend/rpa/harness/live_agent_eval.py`.
- Read `RpaClaw/backend/rpa/harness/run_harness_profile.py`.
- Read `RpaClaw/backend/rpa/harness/run_live_agent_eval.py`.
- Read `RpaClaw/backend/rpa/recording_runtime_agent.py` signatures for `region_context`.
- Read focused tests for profile runner, live agent eval, and user input replay.

Retrieval conclusion:

- F012 should become the full-live execution bottom; it already handles controlled
  HTML, Playwright, real `RecordingRuntimeAgent.run()`, candidate-lite generation,
  and post-capture checks.
- F016 should provide the source natural-language user input events and region context
  facts; manual events stay deterministic in this slice.
- `profile_runner.py` should remain a dispatch/wrapper module, not absorb full-live
  scenario construction or post-capture logic.
- Generated full-live assets must be isolated from governed source assets and remain
  candidate-lite/profile artifacts.

Vision Gate:

```text
Vision Gate: ready to implement
Mode: Entry Gate
Original intent:
- Add a unified v1 full-live profile that triggers the real RecordingRuntimeAgent /
  Planner / LLM path in a controlled environment.
Alignment:
- New full_live_profile.py reuses F012 and F016, while profile_runner only dispatches
  and renders unified summaries.
Drift risks:
- live URL oracle, direct Agent UI driving, automatic diagnosis, automatic promotion,
  region-specific branches, or rewriting F012/F016 into a giant runner.
Vision Anchor:
- F017 Feature plus Phase 5 plan, v1 design, F016/EV-016, F012/EV-012, ADR-003,
  and usage guide.
Reviewer policy:
- independent review recommended before readiness because this is a high-risk
  Harness execution/report contract slice.
Required next action:
- follow TDD: write RED tests first, then minimal implementation, then verification,
  report generation, and Evidence closeout.
```

Delegation Gate:

```text
Delegation Gate: authorized
Mode:
- implementation
Task class:
- high-risk
Authorization source:
- explicit current request: "复杂任务可以拆分给subagent去执行"
Triggers:
- work spans docs, runner dispatch, full-live module, CLI, tests, and reports
- independent sidecar exploration can reduce anchoring without blocking local work
Decision:
- one read-only explorer is authorized for implementation-shape review
Residual risk:
- final integration and verification remain local; subagent output is advisory
Allowed next action:
- continue local pre-work and TDD while the explorer analyzes code boundaries
```

## Commands

RED tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py
```

Initial RED result:

```text
ModuleNotFoundError: No module named 'backend.rpa.harness.full_live_profile'
```

Focused GREEN tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py
```

Result:

```text
6 passed in 10.34s
```

Focused regression:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py `
  RpaClaw/backend/tests/test_rpa_harness_profile_runner.py `
  RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py `
  RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py
```

Result:

```text
Initial closeout: 32 passed in 25.38s
After independent review follow-up fixes: 35 passed in 29.84s
After F017.1 review follow-up fixes: 37 passed in 33.07s
After F017.2 path containment fixes: 39 passed in 38.45s
```

Syntax check:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m py_compile `
  RpaClaw\backend\rpa\harness\full_live_profile.py `
  RpaClaw\backend\rpa\harness\live_agent_eval.py `
  RpaClaw\backend\rpa\harness\profile_runner.py `
  RpaClaw\backend\rpa\harness\run_harness_profile.py
```

Result:

```text
exit code 0
```

F017.1 RED tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py
```

Initial F017.1 RED result:

```text
3 failed, 8 passed
- missing source_region_context / runtime_region_context in controlled fixture report
- FileNotFoundError escaped when selected event before.html was missing
- summary CLI reran full-live profile instead of rendering existing machine report
```

F017.2 RED tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py `
  -k "before_html_path_outside_source_asset or absolute_before_html_path"
```

Initial F017.2 RED result:

```text
2 failed
- `../../outside-secret.html` escaped the source asset directory and reached live-agent execution
- absolute `before_page.html_path` was rejected only after path handling, not by an explicit fixture contract
```

F017.2 focused GREEN result:

```text
2 passed, 11 deselected in 0.46s
13 passed in 12.89s
```

Controlled bootstrap full-live report generation with injected fake planner:

```powershell
$env:PYTHONPATH='RpaClaw'
@'
import asyncio, json
from pathlib import Path
from backend.rpa.harness.full_live_profile import run_full_live_profile, render_full_live_profile_summary

root = Path(r'E:\Work-Project\OtherWork\ScienceClaw')
assets = root / 'data' / 'rpa_harness_assets_bootstrap'
generated = root / 'docs' / 'rpa' / 'harness' / 'reports' / 'f017-generated-assets'
json_path = root / 'docs' / 'rpa' / 'harness' / 'reports' / '2026-05-28-f017-full-live-profile.json'
md_path = root / 'docs' / 'rpa' / 'harness' / 'reports' / '2026-05-28-f017-full-live-profile.md'

async def planner(payload):
    return {
        'description': 'Return the visible page text for controlled full-live profile validation',
        'output_key': 'full_live_text',
        'code': """
async def run(page, results):
    return (await page.locator('body').inner_text()).strip()
""",
    }

async def main():
    report = await run_full_live_profile(assets, generated_assets_root=generated, planner=planner)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    md_path.write_text(render_full_live_profile_summary(report, machine_report_path=json_path, lang='zh'), encoding='utf-8')
    print(report['summary'])

asyncio.run(main())
'@ | python -
```

Result:

```text
status=passed
failure_category=
selected_input_event_count=2
fixture_build_failure_count=0
planner_invocation_count=2
generated_asset_ids=[
  hcap-live-hcap-4be6265f43eb42dfa259182207aa64cc-step-3,
  hcap-live-hcap-de463b7bb608482e9b5bcdd5b78a224e-step-3
]
generated_trace_ids=[
  trace-4ef1a0fe4dd24b5fb518c644212d4316,
  trace-5285c9344cd34ce3b7ff01f1fd2dc0b2
]
post_capture_warning_count=0
```

CLI full-live JSON write and no-input failure behavior:

```powershell
$empty = 'E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current\f017-empty-assets'
New-Item -ItemType Directory -Force -Path $empty | Out-Null
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets $empty `
  --profile full-live `
  --generated-assets E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current\f017-empty-generated `
  --output E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current\f017-cli-empty-full-live.json
```

Result:

```text
exit_code=1
profile.name=full-live
profile.uses_live_planner=true
summary.failure_category=no-full-live-input-events
```

Strict knowledge check:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Result:

```text
Scanned 216 markdown file(s). Checked 38 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## Results

Implemented. F017 adds the `full-live` profile integration slice.

New behavior:

- `RpaClaw/backend/rpa/harness/full_live_profile.py` builds full-live scenarios
  from F016 natural-language input events.
- `live_agent_eval.py` now accepts optional scenario `region_context` and passes it
  generically to `RecordingRuntimeAgent.run(...)`.
- `profile_runner.py` dispatches `profile="full-live"` while preserving deterministic
  default behavior.
- `run_harness_profile.py` supports `--generated-assets`, `--model-config-json`, and
  `--model-config-file` for full-live runs. CLI default does not inject a fake planner.
- Generated assets are isolated from source assets and a same-root generated path is
  rejected.
- Empty full-live input returns failed/insufficient evidence, not passed.
- Full-live reports include profile metadata, source asset ids, selected input events,
  controlled fixture metadata, planner count, generated trace/asset ids, post-capture
  summaries, failures, trust limits, and governance boundary.

Independent review follow-up:

- Accepted P1: generated candidate-lite/profile artifact post-capture warnings were
  initially able to make the full-live profile blocking. Fixed by classifying
  `post-capture-regression-warning` as `warning-only-generated-asset`, with a focused
  regression test.
- Accepted P2: generated asset root isolation initially rejected only exact source-root
  equality. Fixed by rejecting descendants of the source governed asset root, with a
  focused regression test.
- Accepted P2: deterministic CLI initially parsed full-live-only model config options
  before dispatch. Fixed by loading model config only for `profile=full-live`, with a
  focused regression test proving deterministic ignores those options.

F017.1 review follow-up:

- Accepted P1: F016 region context originally reached the report and scenario, but
  Runtime compacting could receive an empty selected-region context because F016 uses
  `target_evidence` / `signals` while Runtime expects top-level fields or an `evidence`
  object. Fixed by normalizing source region facts into Runtime shape while preserving
  the source shape in report metadata. Focused tests now assert the planner payload has
  region-scoped snapshot evidence.
- Accepted P2: missing or damaged `before.html` originally escaped as `FileNotFoundError`.
  Fixed by converting fixture-build failures into per-event JSON-first failures and
  continuing other runnable events.
- Accepted P3: summary CLI originally reran the profile even when `--machine-report`
  pointed to an existing JSON report. Fixed by reading existing machine reports for
  summary rendering.

F017.2 review follow-up:

- Accepted P1: `before_page.html_path` could escape the governed source asset
  directory through `..` traversal or absolute paths before controlled fixture HTML
  was read. Fixed by resolving and validating source root, source asset directory,
  and candidate HTML path before `read_text()`. Focused tests now assert traversal
  and absolute paths become JSON-first fixture-build failures, planner is not
  invoked, and external file contents do not appear in the machine report.

## Artifacts

- Feature: `docs/features/F017-rpa-harness-v1-full-live-profile-integration.md`
- Evidence: `docs/evidence/EV-017-rpa-harness-v1-full-live-profile-integration.md`
- Plan: `docs/rpa/harness/f017-rpa-harness-v1-phase-5-plan.md`
- Runner module: `RpaClaw/backend/rpa/harness/full_live_profile.py`
- Live eval extension: `RpaClaw/backend/rpa/harness/live_agent_eval.py`
- Profile dispatch: `RpaClaw/backend/rpa/harness/profile_runner.py`
- CLI dispatch: `RpaClaw/backend/rpa/harness/run_harness_profile.py`
- Focused tests: `RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py`
- Machine report: `docs/rpa/harness/reports/2026-05-28-f017-full-live-profile.json`
- Markdown summary: `docs/rpa/harness/reports/2026-05-28-f017-full-live-profile.md`
- Generated profile artifacts root: `docs/rpa/harness/reports/f017-generated-assets`

## Residual Risk

- Real internal LLM behavior was not validated on this machine; tests and the stored
  bootstrap report use fake planner injection for determinism while CLI defaults to
  the real planner path.
- The first slice only covers natural-language input events.
- Controlled fixture fidelity depends on captured `before.html`, checkpoint quality,
  and source trace event facts. Missing fixture files are now reported as Harness
  failures rather than uncaught exceptions.
- Generated assets are candidate-lite/profile artifacts and still need human review
  before any trusted promotion.
- The stored bootstrap report uses public bootstrap assets and a simple fake planner
  that returns visible body text; it proves the full-live integration path, not real
  model quality.
- A v1 stabilization/closeout slice may be useful after independent review if stronger
  report normalization or internal full-live scenarios are requested.
- Independent review remains recommended before accepting F017 readiness.

## Reviewer Status

A read-only sidecar explorer reviewed the implementation shape and confirmed the
main direction: add `full_live_profile.py` as a profile/report adapter, reuse F012
`run_live_agent_eval()`, keep `profile_runner.py` small, preserve deterministic
default behavior, isolate generated assets from source assets, keep candidate-lite
warning-only, and pass `region_context` generically.

Independent code review found seven total boundary issues across three review rounds; all
accepted findings were fixed with RED/GREEN tests and adjacent regression reruns.
Human review is still recommended before treating F017 as accepted because this is a
high-risk Harness execution/report contract slice.

## Notes

- `docs/rpa/harness/RPA-Harness-v1-设计.md` is a compatibility index; the canonical
  v1 design source remains
  `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Existing untracked workspace files predate this slice and are intentionally ignored
  unless Phase 5 creates new report artifacts.
- Local tests may inject a fake planner for determinism. CLI default behavior must not
  inject a fake planner.

## Closeout

Implementation done. F017.2 follow-up fixes are in place. Focused tests and adjacent
regression tests pass. Strict knowledge validation passes. F017 is ready for human
review; a small stabilization slice should be driven by internal full-live scenario
needs rather than by the already-addressed review findings.
