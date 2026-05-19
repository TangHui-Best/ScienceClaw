---
id: F008
doc_kind: feature
status: active
created: 2026-05-18
updated: 2026-05-18
---

# F008: Skill Replay E2E Runner

## Goal

Add the first governed Skill Replay E2E runner slice so Harness can compile
trace evidence into a Skill, execute it against a controlled replay fixture,
and compare the replay result with expected signals.

## Vision Anchor

- Original request: continue ScienceClaw RPA Harness work after F007 and enter
  F008 for Skill Replay E2E.
- User pain point: governed regression now proves offline snapshot and compiler
  behavior, but it still does not prove that generated `skill.py` can execute
  against a controlled replay page/provider and produce expected output.
- Desired outcome for F008.0: define a replay runner contract, execute a
  minimal compiled Skill against a controlled fixture page, validate expected
  replay signals, and expose the result as an independent governed runner
  signal.
- Desired outcome for F008.1: later connect the real governed candidate asset
  `hcap-4be6265f43eb42dfa259182207aa64cc` to a controlled replay
  target/provider without touching live GitHub or restoring direct Agent chat.
- Non-goals:
  - Do not fix planner behavior.
  - Do not fix `TraceSkillCompiler` hard-coded observed values unless replay
    exposes a separate owner bug for another Feature.
  - Do not expand the governed asset set.
  - Do not restore `rpa-eval-app` direct Agent chat as the golden runner.
  - Do not introduce GitHub-specific replay rules.
  - Do not use live URL state as the oracle.
- Exit Gate source: this Feature, [EV-008](../evidence/EV-008-skill-replay-e2e-runner.md),
  [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md),
  [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md),
  [F007](F007-production-snapshot-core-chain-regression.md), and
  [EV-007](../evidence/EV-007-production-snapshot-core-chain-regression.md).

## Current Status

Active. F008.0 and F008.1 are implemented and verified; commit closeout remains
pending.

## Links

- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Previous Feature: [F007 Production Snapshot Core-chain Regression](F007-production-snapshot-core-chain-regression.md)
- Previous Evidence: [EV-007 Production Snapshot Core-chain Regression Evidence](../evidence/EV-007-production-snapshot-core-chain-regression.md)
- Evidence: [EV-008 Skill Replay E2E Runner Evidence](../evidence/EV-008-skill-replay-e2e-runner.md)
- Backlog: [Backlog](../BACKLOG.md)

## Acceptance Criteria

- [x] A Skill Replay E2E runner contract exists with stable JSON summary and
  per-step replay items.
- [x] The runner compiles trace events with `TraceSkillCompiler`, executes the
  resulting Skill against a controlled fixture page, and validates expected
  state/replay signals.
- [x] The runner reports replay failures with bounded categories instead of
  hiding them inside generic exceptions.
- [x] Governed regression includes Skill Replay as an independent runner signal
  without making zero replay-eligible assets a false failure for F008.0.
- [x] Existing governed candidate asset still passes governed offline
  regression; F008.0 does not require live GitHub or direct Agent chat.
- [x] Focused backend tests, governed summary, and strict Harness knowledge
  checks pass.
- [x] EV-008 records RED/GREEN verification, residual risk, reviewer status,
  and closeout status before F008 advances beyond F008.0.
- [x] The first real governed candidate asset
  `hcap-4be6265f43eb42dfa259182207aa64cc` declares `skill_replay_e2e`
  eligibility and `skill_replay` coverage only after controlled replay passes.
- [x] Governed regression reports `skill_replay_checked=3` and
  `skill_replay_failed=0` for the real bootstrap candidate without touching
  live GitHub.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-008 Skill Replay E2E Runner Evidence](../evidence/EV-008-skill-replay-e2e-runner.md).

## Next Step

Commit and close out F008, then decide whether the next Feature should
strengthen replay from per-step controlled HTML replay into full SOP stateful
replay.
