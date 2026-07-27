---
id: ADR-003
doc_kind: adr
status: accepted
scope: project
feature_ids: [F002]
feature_refs:
  - docs/features/F002-rpa-harness-v0.md
decision_area: rpa-golden-evaluation
created: 2026-05-18
updated: 2026-05-19
---

# ADR-003: RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat

## Context

The project already contains `rpa-eval-app`, a local golden evaluation
application with resettable business pages and YAML cases. Its current runner
starts an RPA session, navigates to a page, sends a natural-language task to
Agent chat, and verifies business state through API assertions.

That is useful for measuring online task completion, but it does not prove the
core product path that matters most for RPA skill generation:

```text
SOP intent -> recorded step evidence -> trace -> Skill compilation -> replay
```

The Harness work started because core-chain changes such as DOM snapshot
compression, trace normalization, and `TraceSkillCompiler` behavior were risky
to change without reusable real page assets. A direct Agent chat runner cannot
answer which captured HTML, step intent, trace, snapshot, or compiler baseline
changed. It also cannot reliably distinguish a model/runtime task failure from
a trace-to-Skill regression.

Live Agent E2E, where another agent operates the RPA Agent UI like a human,
would be even noisier as the primary oracle. It would add product UI state,
nested browser automation, model variance, and timing failures on top of the
RPA core chain.

## Decision

RPA golden evaluation will be centered on governed scenario assets, not direct
Agent chat against live pages.

The primary execution modes are:

1. Offline Core-Chain Regression: consume captured HTML, step intent, trace,
   snapshot baselines, compiler baselines, and expected signals without opening
   the live website.
2. Stateful SOP Capture-to-Skill Regression: consume governed scenario assets
   as a controlled recording input provider so the RPA Agent core still sees an
   equivalent recording session, produces accepted trace evidence, and compiles
   a Skill without requiring live human UI operation during every evaluation.
3. Skill Replay E2E: compile captured SOP or trace evidence into a Skill,
   execute that Skill in a controlled replay environment, and compare final
   results with expected signals.

Live Agent E2E is not the current primary path. It may be added later as a
smoke or demo layer, but it must not replace asset-based offline regression or
Skill Replay E2E as the Harness correctness oracle.

`rpa-eval-app` remains valuable as a controlled business scenario provider:

- pages for procurement, suppliers, contracts, approvals, and reports
- resettable backend fixtures
- business-state assertion APIs
- download and audit-event fixtures

Its current direct Agent chat runner is not the main golden evaluation path.
Future work may adapt its pages and APIs as replay targets for governed Harness
scenario assets.

## Alternatives

- Keep using the existing `rpa-eval-app` runner as the golden evaluation main
  path. Rejected because it tests online Agent task completion rather than the
  SOP to trace to Skill to replay chain.
- Build Live Agent E2E first. Rejected because the resulting signal would be too
  noisy and expensive for core-chain regression decisions.
- Use only offline snapshot/compiler regression. Rejected because the project
  still needs Skill Replay E2E to validate generated Skills against final
  behavior.
- Use only live URLs as the oracle. Rejected because page data, auth,
  permissions, A/B tests, timing, and dynamic ordering make live URLs unstable
  as the primary correctness source.

## Consequences

- F003 should define a Golden Scenario Asset Model instead of extending the
  existing direct Agent chat runner.
- Captured HTML, step intent, trace, expected signals, and baselines become the
  durable unit of golden evaluation.
- Stateful Capture-to-Skill work should aim for internal equivalence: asset
  replay differs from human recording at the outer input boundary, while the
  RPA Agent recording, trace, compiler, and optional replay chain remains the
  same product path.
- `rpa-eval-app` should be treated as a reusable scenario service, not as the
  owner of the golden evaluation architecture.
- Compiler issues such as hard-coded observed values should be exposed by
  Harness assets, fixed in `TraceSkillCompiler` or the owning RPA component,
  and then validated through the asset set.
- Future reviewers should reject changes that make live task completion the
  only proof for snapshot, trace, compiler, or Skill replay correctness.

## Evidence

- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Feature: [F002 RPA Harness v0](../features/F002-rpa-harness-v0.md)
- Evidence: [EV-002 RPA Harness v0 Evidence](../evidence/EV-002-rpa-harness-v0.md)
- Existing eval app: `rpa-eval-app/README.md`
- Harness regression strategy: [RPA Harness Regression Strategy](../rpa/harness/regression-strategy.md)

## Decision Boundary

### Applies To

The decision scope described in the original Context and Decision sections.

### Does Not Apply To

Areas not explicitly covered by the original decision; this migration does not broaden its authority.

## Rejected Options

Existing alternatives remain authoritative where recorded in the original ADR. This migration introduces no new rejected architecture option.

## Before Changing This Decision

Read the original Context, Decision, Consequences, linked Feature, and Evidence. Record a successor ADR or explicit update before changing this durable boundary.
