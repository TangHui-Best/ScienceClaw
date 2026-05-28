# F018 RPA Harness v1 Closeout / Stabilization Plan

## Goal

Close out RPA Harness v1 by making the already-delivered Phase 0-5 capabilities
understandable, verifiable, and recoverable from durable project memory.

This is not Phase 6. The plan is intentionally documentation and verification heavy:
it should converge the entrypoint, label artifact identity, rerun the v1 acceptance
checklist, and record residual risk.

## Scope

Do:

- Upgrade `docs/rpa/harness/rpa-harness-v1-design.md` into the v1 total entrypoint.
- Clarify the v1 journey:

```text
capture -> review -> promote -> deterministic -> user-input replay -> full-live
  -> Agent analysis -> human decision
```

- Document the three main commands:
  - deterministic profile;
  - user-input replay;
  - full-live profile.
- State when to run each profile and what each profile proves.
- State what results may be interpreted and what must not be overclaimed.
- Mark `docs/rpa/harness/reports/f017-generated-assets/...` and the F018 generated
  asset root as Evidence/profile artifacts, not governed asset pools.
- Run and record the full v1 acceptance checklist.
- Decide whether internal controlled full-live scenarios are v1 blockers or v1.1/backlog.

Do not:

- Add runners.
- Expand full-live to all manual UI events.
- Add CI blocking.
- Add automatic promotion.
- Move generated artifacts into governed asset roots.
- Delete or archive old docs.
- Change deterministic/user-input/full-live execution semantics.
- Add region-selection special architecture.

## Implementation Tasks

### Task 1: Entrypoint rewrite

Rewrite `docs/rpa/harness/rpa-harness-v1-design.md` from compatibility index into
the v1 total entrypoint.

Required sections:

- v1 vision and core boundary;
- user journey;
- asset lifecycle and governance;
- profile selection guide;
- deterministic profile command and interpretation limits;
- user-input replay command and interpretation limits;
- full-live profile command and interpretation limits;
- report interpretation rules;
- generated artifact identity;
- CI and promotion boundaries;
- v1 closeout and v1.1/backlog boundary.

### Task 2: Usage guide note

Add a small F018 closeout note to `usage-and-triage-guide.md` that points users to
the new entrypoint and warns that generated profile artifacts under report folders are
Evidence artifacts unless reviewed and promoted.

### Task 3: Acceptance rerun

Run:

```powershell
$env:PYTHONPATH='RpaClaw'

python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile deterministic `
  --output docs\rpa\harness\reports\2026-05-28-f018-deterministic-profile.json

python -m backend.rpa.harness.run_catalog `
  --assets data\rpa_harness_assets_bootstrap `
  --format lifecycle `
  --output docs\rpa\harness\reports\2026-05-28-f018-lifecycle-summary.json

python -m backend.rpa.harness.run_catalog `
  --assets data\rpa_harness_assets_bootstrap `
  --format golden-eligibility `
  --output docs\rpa\harness\reports\2026-05-28-f018-golden-eligibility.json

python -m backend.rpa.harness.run_user_input_replay `
  --assets data\rpa_harness_assets_bootstrap `
  --output docs\rpa\harness\reports\2026-05-28-f018-user-input-replay.json

python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile full-live `
  --generated-assets docs\rpa\harness\reports\f018-generated-assets `
  --output docs\rpa\harness\reports\2026-05-28-f018-full-live-profile.json
```

Then run focused regression tests:

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

Run strict Harness validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py `
  --root E:\Work-Project\OtherWork\ScienceClaw `
  --docs-path docs `
  --strict
```

### Task 4: Evidence closeout

Update EV-018 with:

- actual command results;
- key JSON summary facts;
- focused test result;
- strict knowledge check result;
- sidecar audit result if available;
- generated artifact identity;
- internal controlled full-live scenario decision;
- residual risk;
- closeout verdict.

Update F018 to `ready_for_review` only after EV-018 records verification and residual
risk.
