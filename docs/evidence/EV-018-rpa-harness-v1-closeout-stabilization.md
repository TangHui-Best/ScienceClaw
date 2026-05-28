---
id: EV-018
doc_kind: evidence
title: RPA Harness v1 Closeout / Stabilization Evidence
status: active
scope: project
feature_ids: [F018]
feature_refs:
  - docs/features/F018-rpa-harness-v1-closeout-stabilization.md
created: 2026-05-28
updated: 2026-05-28
evidence_level: exhaustive
---

# EV-018 RPA Harness v1 Closeout / Stabilization Evidence

## Scope

Evidence for F018: RPA Harness v1 closeout / stabilization.

This is not Phase 6. It does not add runners, extend full-live manual UI event
coverage, add CI blocking, automate promotion, move generated artifacts into the
governed asset pool, or change deterministic/user-input/full-live execution semantics.

The intended closeout judgment is whether Phase 0-5 can now be understood and used
as one v1 loop:

```text
capture -> review -> promote -> deterministic -> user-input replay -> full-live
  -> Agent analysis -> human decision
```

## Entry Gate

Start Gate:

```text
Start Gate: needs retrieval -> satisfied; needs vision gate -> satisfied;
needs feature/plan -> satisfied by F018, EV-018, and the F018 plan before edits
Task class: high-risk
Risk triggers:
- Harness closeout and handoff semantics
- v1 source-of-truth entrypoint
- generated full-live artifact governance boundary
- full-live interpretation and overclaiming limits
- possible drift toward Phase 6, CI blocking, automatic promotion, or live URL oracle
Delegation decision:
- authorized for read-only sidecar audit because the user explicitly allowed subagents
Bug attribution:
- not triggered; this is stabilization/closeout, not a bugfix
Required pre-work:
- retrieve F013-F017 / EV-013-EV-017, v1 designs, ADR-003, usage guide
- run Vision Gate and Doc Lifecycle judgment
- create Feature/Evidence/Plan before documentation edits or validation runs
Allowed next action:
- update the v1 entrypoint and usage-guide notes, then run full v1 acceptance checklist
```

Knowledge Retrieval:

- Read `docs/rpa/harness/rpa-harness-v1-design.md`.
- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read F013 through F017 Feature pages and EV-013 through EV-017 Evidence records.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.

Retrieval conclusion:

- F013-F017 are all `ready_for_review`.
- deterministic profile is the stable default regression path.
- lifecycle / promotion guardrails govern `draft` / `candidate-lite` / `candidate` /
  `golden`.
- user-input replay proves scripted boundary extraction/injection from captured facts.
- full-live profile provides the controlled high-fidelity path for natural-language
  events. Real `Planner / LLM` evidence requires a no-injected-planner run with model
  credentials; injected deterministic planner evidence only proves profile wiring,
  Runtime invocation, trace/artifact generation, and post-capture checks.
- F017/F018 generated assets under report folders are full-live Evidence/profile
  artifacts, not governed source asset pools.

Vision Gate:

```text
Vision Gate: ready to implement
Mode: Entry Gate
Original intent:
- Close out v1 so future Agents and humans can understand what Harness v1 is, how to
  run it, what it proves, and where v1 stops.
Alignment:
- Documentation convergence plus acceptance rerun is the smallest coherent path.
Drift risks:
- Phase 6 expansion, CI blocking, automatic promotion, live URL oracle, outer Agent UI
  control, automatic diagnosis, generated artifact promotion-by-default.
Vision Anchor:
- F018 Feature plus F013-F017, v1 design, ADR-003, and usage guide.
Reviewer policy:
- independent review recommended; read-only sidecar audit authorized.
Required next action:
- update v1 entrypoint and artifact identity notes, run acceptance checklist, update EV-018.
```

Doc Lifecycle:

```text
Doc Lifecycle: lightweight entrypoint convergence
Decision:
- Upgrade docs/rpa/harness/rpa-harness-v1-design.md from compatibility index to the
  v1 total entrypoint.
- Keep docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md as the detailed
  design source linked from the entrypoint.
- Keep F013-F017 plans and Evidence records active as historical delivery anchors.
- Do not archive, delete, or broadly rewrite old docs in F018.
```

Delegation Gate:

```text
Delegation Gate: authorized
Mode:
- implementation
Task class:
- high-risk
Authorization source:
- explicit current request allowing subagents for complex tasks
Decision:
- one read-only sidecar audit may run in parallel; main documentation edits and
  verification integration remain local. Sidecar output is advisory review signal,
  not the sole closeout authority.
Residual risk:
- sidecar output is advisory; final closeout remains backed by local verification and
  human review.
```

## Commands

Environment repair before full-live rerun:

```powershell
python -m pip install langchain-openai==1.1.8 langchain-core
```

Result:

```text
exit code 0
Reason: the first real full-live Planner attempt wrote a debug artifact showing
ModuleNotFoundError: No module named 'langchain_openai'. The package is declared in
RpaClaw/backend/requirements.txt but was missing from the current Python environment.
```

Deterministic profile JSON:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile deterministic `
  --output docs\rpa\harness\reports\2026-05-28-f018-deterministic-profile.json
```

Result:

```text
exit code 0
summary.status = passed
summary.selected_asset_count = 2
summary.excluded_asset_count = 0
summary.first_failure_category = ""
interpretation.verdict = no meaningful change
interpretation.evidence_limits include:
- No baseline comparison report was supplied
- Passing covered assets does not prove global RPA health
```

Deterministic profile summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile deterministic `
  --format summary `
  --lang zh `
  --output docs\rpa\harness\reports\2026-05-28-f018-deterministic-profile.md `
  --machine-report docs\rpa\harness\reports\2026-05-28-f018-deterministic-profile.json
```

Result:

```text
exit code 0
```

Lifecycle summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_catalog `
  --assets data\rpa_harness_assets_bootstrap `
  --format lifecycle `
  --output docs\rpa\harness\reports\2026-05-28-f018-lifecycle-summary.json
```

Result:

```text
exit code 0
summary.asset_count = 2
summary.lifecycle_distribution = {"candidate": 2}
summary.asset_statuses = {"active": 2}
summary.sensitivity = {"local-only": 1, "repo-safe": 1}
```

Golden eligibility:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_catalog `
  --assets data\rpa_harness_assets_bootstrap `
  --format golden-eligibility `
  --output docs\rpa\harness\reports\2026-05-28-f018-golden-eligibility.json
```

Result:

```text
exit code 0
summary.asset_count = 2
summary.eligible_count = 2
summary.ineligible_count = 0
eligible_asset_ids =
- hcap-4be6265f43eb42dfa259182207aa64cc
- hcap-de463b7bb608482e9b5bcdd5b78a224e
Note: eligibility is not promotion; human approval is still required for golden.
```

User-input replay JSON:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay `
  --assets data\rpa_harness_assets_bootstrap `
  --output docs\rpa\harness\reports\2026-05-28-f018-user-input-replay.json
```

Result:

```text
exit code 0
summary.status = passed
selected_asset_count = 2
blocking_asset_count = 2
replayed_event_count = 6
boundary_injection_count = 6
blocking_failure_count = 0
event_kinds = {"click": 2, "natural_language_instruction": 2, "navigation": 2}
injected_boundaries = {
  "scripted_manual_input_boundary": 2,
  "scripted_natural_language_instruction_boundary": 2,
  "scripted_navigation_boundary": 2
}
```

User-input replay summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay `
  --assets data\rpa_harness_assets_bootstrap `
  --format summary `
  --lang zh `
  --output docs\rpa\harness\reports\2026-05-28-f018-user-input-replay.md `
  --machine-report docs\rpa\harness\reports\2026-05-28-f018-user-input-replay.json
```

Result:

```text
exit code 0
```

Full-live real Planner CLI attempt:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile full-live `
  --generated-assets docs\rpa\harness\reports\f018-generated-assets `
  --output docs\rpa\harness\reports\2026-05-28-f018-full-live-profile.json
```

First result:

```text
exit code 1
debug root cause: ModuleNotFoundError: No module named 'langchain_openai'
```

After installing the declared dependency, rerun result:

```text
exit code 1
machine report preserved as:
docs/rpa/harness/reports/2026-05-28-f018-full-live-profile-real-planner-attempt.json
summary.status = failed
summary.failure_category = live-agent-output-missing-signal
summary.selected_input_event_count = 2
summary.planner_invocation_count = 0
blocking_failure_count = 2
debug root cause: OpenAIError: Missing credentials. Please pass an api_key or set OPENAI_API_KEY.
```

Attribution:

- The CLI default real Planner path was executed and failed because the local
  environment does not provide `DS_API_KEY` / `OPENAI_API_KEY` credentials for the
  OpenAI-compatible planner.
- This does not prove the v1 full-live integration contract is broken; it proves the
  current workstation cannot run the real default Planner without model credentials.
- The failed attempt is kept as Evidence and must not be overread as product regression.
- The passing controlled fake-planner report has `profile.uses_live_planner=true`
  because that is the profile capability flag, but this F018 acceptance run used an
  injected deterministic planner. Its `planner_invocation_count=2` counts injected
  planner calls, not real LLM calls.

Controlled full-live bootstrap report with injected deterministic planner:

```powershell
$env:PYTHONPATH='RpaClaw'
@'
import asyncio, json
from pathlib import Path
from backend.rpa.harness.full_live_profile import run_full_live_profile, render_full_live_profile_summary

root = Path(r'E:\Work-Project\OtherWork\ScienceClaw')
assets = root / 'data' / 'rpa_harness_assets_bootstrap'
generated = root / 'docs' / 'rpa' / 'harness' / 'reports' / 'f018-generated-assets'
json_path = root / 'docs' / 'rpa' / 'harness' / 'reports' / '2026-05-28-f018-full-live-profile.json'
md_path = root / 'docs' / 'rpa' / 'harness' / 'reports' / '2026-05-28-f018-full-live-profile.md'

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
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))

asyncio.run(main())
'@ | python -
```

Result:

```text
exit code 0
summary.status = passed
selected_input_event_count = 2
fixture_build_failure_count = 0
planner_invocation_count = 2
generated_asset_ids =
- hcap-live-hcap-4be6265f43eb42dfa259182207aa64cc-step-3
- hcap-live-hcap-de463b7bb608482e9b5bcdd5b78a224e-step-3
generated_trace_ids =
- trace-6c692355d6794bb9a2b0d9e1dacc14c0
- trace-c12d3789595d4900b1c313058a179477
blocking_failure_count = 0
post_capture_warning_count = 0
```

Focused regression tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current `
  RpaClaw/backend/tests/test_rpa_harness_profile_runner.py `
  RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py `
  RpaClaw/backend/tests/test_rpa_harness_catalog.py `
  RpaClaw/backend/tests/test_rpa_harness_asset_review.py `
  RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py
```

Result:

```text
52 passed, 1 warning in 38.30s
Warning: langchain_core Pydantic V1 compatibility warning on Python 3.14.
```

Strict Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py `
  --root E:\Work-Project\OtherWork\ScienceClaw `
  --docs-path docs `
  --strict
```

Result:

```text
exit code 0
Scanned 222 markdown file(s). Checked 40 knowledge artifact(s). Errors: 0. Warnings: 0.
```

F018.1 review follow-up link check:

```powershell
$base = Resolve-Path docs\rpa\harness
$links = @(
  '../../features/F013-rpa-harness-v1-asset-driven-user-input-replay.md',
  '../../evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md',
  '../../features/F014-rpa-harness-v1-evidence-report-trust-loop.md',
  '../../evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md',
  '../../features/F015-rpa-harness-v1-asset-lifecycle-operationalization.md',
  '../../evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md',
  '../../features/F016-rpa-harness-v1-asset-driven-user-input-replay.md',
  '../../evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md',
  '../../features/F017-rpa-harness-v1-full-live-profile-integration.md',
  '../../evidence/EV-017-rpa-harness-v1-full-live-profile-integration.md',
  '../../features/F018-rpa-harness-v1-closeout-stabilization.md',
  '../../evidence/EV-018-rpa-harness-v1-closeout-stabilization.md',
  '../../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md',
  'usage-and-triage-guide.md'
)
foreach ($l in $links) {
  $p = Join-Path $base $l
  if (-not (Test-Path $p)) { Write-Error "Missing $l"; exit 1 }
}
'all source-map links exist'
```

Result:

```text
exit code 0
all source-map links exist
```

F018.1 strict Harness validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py `
  --root E:\Work-Project\OtherWork\ScienceClaw `
  --docs-path docs `
  --strict
```

Result:

```text
exit code 0
Scanned 222 markdown file(s). Checked 40 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## Artifacts

- Feature: `docs/features/F018-rpa-harness-v1-closeout-stabilization.md`
- Evidence: `docs/evidence/EV-018-rpa-harness-v1-closeout-stabilization.md`
- Plan: `docs/rpa/harness/f018-rpa-harness-v1-closeout-stabilization-plan.md`
- v1 entrypoint: `docs/rpa/harness/rpa-harness-v1-design.md`
- Usage guide: `docs/rpa/harness/usage-and-triage-guide.md`
- Deterministic report: `docs/rpa/harness/reports/2026-05-28-f018-deterministic-profile.json`
- Deterministic summary: `docs/rpa/harness/reports/2026-05-28-f018-deterministic-profile.md`
- Lifecycle report: `docs/rpa/harness/reports/2026-05-28-f018-lifecycle-summary.json`
- Golden eligibility report: `docs/rpa/harness/reports/2026-05-28-f018-golden-eligibility.json`
- User-input replay report: `docs/rpa/harness/reports/2026-05-28-f018-user-input-replay.json`
- User-input replay summary: `docs/rpa/harness/reports/2026-05-28-f018-user-input-replay.md`
- Full-live controlled report: `docs/rpa/harness/reports/2026-05-28-f018-full-live-profile.json`
- Full-live controlled summary: `docs/rpa/harness/reports/2026-05-28-f018-full-live-profile.md`
- Full-live real Planner failed attempt:
  `docs/rpa/harness/reports/2026-05-28-f018-full-live-profile-real-planner-attempt.json`
- Generated profile artifact root: `docs/rpa/harness/reports/f018-generated-assets`

## Results

Implemented. F018 upgraded the v1 design path from a compatibility index into the
v1 total entrypoint and added a usage-guide closeout note.

The v1 entrypoint now explains:

- vision and core boundary;
- full user journey;
- asset lifecycle;
- deterministic, user-input replay, and full-live commands;
- when to run which profile;
- what each profile proves and cannot prove;
- JSON-first report interpretation rules;
- generated artifact identity;
- CI, promotion, live URL, and outer Agent UI-control boundaries;
- v1 closeout vs v1.1/backlog boundary.

Generated artifact identity is now explicit:

- `docs/rpa/harness/reports/f017-generated-assets/...` is F017 full-live profile
  Evidence/profile artifact.
- `docs/rpa/harness/reports/f018-generated-assets/...` is F018 full-live profile
  Evidence/profile artifact.
- These report folders are not governed asset pools.
- Individual generated `scenario.json` files may say `candidate-lite` after a passed
  controlled full-live run, but the folder-level contract remains profile artifact.
  Future Agents must not pass report folders as default baseline asset roots or promote
  from them without Assisted Review, sensitivity review, expected-signal review, human
  confirmation, and CLI-backed promotion.

Acceptance summary:

- deterministic profile: passed, 2 selected candidate assets, verdict
  `no meaningful change`.
- lifecycle summary: 2 active candidate assets.
- golden eligibility: 2 eligible candidates, still requiring human approval.
- user-input replay: passed, 6 replayed events, 6 boundary injections.
- full-live controlled fake-planner run: passed, 2 selected natural-language events,
  2 injected planner invocations, 2 generated profile artifacts; this proves the
  controlled profile integration path, not real Planner/LLM quality.
- full-live real Planner CLI attempt: failed due missing local model credentials after
  declared dependency was installed; recorded as environmental residual risk rather
  than accepted product regression.
- focused regression tests: 52 passed, 1 Python 3.14 dependency warning.
- strict Harness knowledge validation: passed.
- F018.1 review follow-up: Source Map links resolve to existing canonical docs, and
  sidecar audit is now a durable summary plus auxiliary review signal instead of the
  sole closeout authority.

Sidecar audit:

- Primary closeout evidence remains the committed EV-018 report set, focused regression
  output, and `knowledge_check.py --strict`.
- Sidecar review is an auxiliary signal recorded below for recovery. The original
  full output lives in the session transcript; the durable recovery summary is this
  section.

### Sidecar Audit Record

Read-only sidecar 1:

- Agent id: `019e6e8c-90e6-7c73-93f0-a26968ea0992`
- Nickname: `Lovelace`
- Scope: F013-F017 Feature/Evidence chain, ADR-003, both v1 design docs, usage guide,
  F017 reports/generated artifacts, and initial F018 anchors.
- Write permission: none used.
- Key conclusions:
  - F018 should close v1 as review-ready/stabilized, not Phase 6 and not human-accepted
    final release.
  - deterministic proves covered governed assets only.
  - user-input replay is scripted/record-only boundary replay from captured facts.
  - full-live is controlled-fixture natural-language path and must not be read as live
    URL oracle, outer Agent UI control, or default blocking.
  - generated report folders such as `f017-generated-assets` and `f018-generated-assets`
    are Evidence/profile artifacts, not governed asset pools, even if individual
    generated `scenario.json` files mention `candidate-lite`.
  - internal controlled full-live scenarios should be v1.1/backlog unless the user
    explicitly makes internal/intranet behavior a v1 completion criterion.
- Applied result:
  - The v1 entrypoint and EV-018 now include the proof matrix, generated artifact
    folder-level rule, fake-planner boundary, and v1.1/internal scenario decision.

Read-only sidecar 2:

- Agent id: `019e6ebb-a415-78f1-911f-5892a7a4558f`
- Nickname: `Pascal`
- Scope: final F018-related changes and f018 report artifacts.
- Write permission: none used.
- Finding:
  - P1: EV-018 and the v1 entrypoint could overclaim the passing controlled full-live
    fake-planner report as real Planner/LLM evidence.
- Applied result:
  - EV-018, the v1 entrypoint, and the usage guide now separate real Planner/LLM
    evidence from injected deterministic planner evidence.

Review follow-up from an additional agent:

- Finding:
  - P1: Source Map links in `docs/rpa/harness/rpa-harness-v1-design.md` used `../`
    and resolved to nonexistent `docs/rpa/features`, `docs/rpa/evidence`, and
    `docs/rpa/decisions`.
  - P2: Sidecar audit was cited as closeout evidence without enough durable recovery
    detail.
- Applied result:
  - Source Map links now use `../../features`, `../../evidence`, and `../../decisions`.
  - This Sidecar Audit Record was added, and closeout wording now treats sidecar review
    as auxiliary rather than the sole authority.

## Internal Controlled Full-Live Scenario Decision

Internal controlled full-live scenarios should not block v1 closeout.

Decision:

- Current bootstrap deterministic, lifecycle, user-input replay, and controlled
  full-live reports are sufficient to close out the v1 core loop as review-ready.
- Real internal model quality and intranet page behavior are not proven by the current
  bootstrap reports.
- If the team needs internal/intranet confidence, create v1.1/backlog with one or two
  internal controlled full-live scenarios.
- Internal scenarios should become a v1 blocker only if the user explicitly redefines
  v1 completion criteria around internal model/intranet behavior.

## Residual Risk

- Bootstrap assets remain narrow and GitHub-focused.
- deterministic profile is process-required but not CI blocking.
- `interpretation.verdict=no meaningful change` is single-run and bounded to the
  covered asset pool.
- user-input replay proves record-only scripted boundary injection, not live UI side
  effects.
- full-live first slice only covers natural-language input events.
- Bootstrap assets do not contain real `type`, `select`, `submit`, or region-selection
  captures; those remain fixture/schema coverage from F016 tests, not bootstrap coverage.
- Controlled fake-planner full-live evidence proves integration path, not real model
  quality.
- Real full-live CLI default Planner attempt cannot pass on this workstation without
  model credentials.
- Generated full-live artifacts are not governed assets until Assisted Review /
  Promotion and human confirmation happen.
- Human review remains pending; F018 is `ready_for_review`, not accepted.

## Notes

- Existing untracked workspace files predate F018 and are intentionally ignored unless
  F018 generates new reports or docs.
- F018 uses the existing branch and asset root; it does not move old report artifacts
  into the governed asset pool.
- The local environment now has `langchain-openai==1.1.8` and `langchain-core`
  installed to satisfy the declared backend requirement for default full-live Planner
  import. This was an environment repair, not a repository code change.

## Closeout

Implementation done. Harness closeout passes for F018 review readiness after
documentation convergence, acceptance reruns, focused regression tests, durable EV-018
evidence, and strict knowledge validation. Sidecar audits are recorded as auxiliary
review signals, not as the sole closeout authority.

F018 should move to human review. Further enhancement should be v1.1/backlog or PR
review work rather than continuing to expand v1.
