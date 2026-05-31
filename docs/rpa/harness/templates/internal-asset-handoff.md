# 内网 RPA Harness Asset Handoff

## Asset

- Asset root:
- Asset id:
- Review packet:
- Execution review:
- Machine reports:

## Human SOP

1.
2.
3.

## Business Acceptance

- Correct final output:
- Required fields:
- Allowed empty cases:
- Disallowed empty cases:
- Important page/region evidence:

## Current Lifecycle

- asset_status:
- promotion_status:
- expected_signals_reviewed: false
- sensitivity_reviewed: false
- sensitivity:
- Allowed next promotion: none | candidate-lite | candidate | golden

## Known Gaps

- Recorded output vs expected result:
- Generated Skill vs expected replay behavior:
- Snapshot / compact evidence gap:
- Compiler / dataflow gap:
- Runtime model config gap:

## Required Commands

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_pool_doctor --assets <asset_root> --format summary --lang zh
python -m backend.rpa.harness.run_asset_review --assets <asset_root> --asset-id <asset_id>
python -m backend.rpa.harness.run_asset_sensitivity_scan --assets <asset_root> --asset-id <asset_id>
python -m backend.rpa.harness.run_harness_profile --assets <asset_root> --profile deterministic --output tmp-harness-profile-deterministic-<slug>.json
```

## Local Model Config

- Config file path:
- Config source: service-derived | temporary-local | not-needed
- Do not paste real API keys, tokens, cookies, or passwords into this handoff.

## Decision Needed From Human

- Is the recorded business result correct?
- Are expected signals reviewed?
- Is sensitivity reviewed?
- May this asset become candidate-lite?
- May this asset become blocking candidate?
