# RPA Harness v1: Asset-Driven User Input Replay

## Purpose

RPA Harness v1 is the product/runtime Harness direction after F003-F010. It
does not replace the v0 capture, asset governance, regression, replay, or
promotion work. It gives those pieces one user-facing mental model:

```text
Use captured assets to script the user input boundary, replay the RPA core
chain in a reproducible way, and let people and Agents judge whether the core
chain became better or worse.
```

The v1 goal is not to create more independent runners. The goal is to make
captured assets the default way to verify RPA core-chain changes before PR
readiness claims, while keeping the execution path stable enough to trust.

## Vision Anchor

The original user need is that RPA changes should be validated by reusable,
explainable, comparable assets instead of one-off live recordings or ad hoc
manual smoke tests.

The important shift is:

```text
Before:
  Fix a page or compiler bug and hope other page shapes still work.

After:
  Capture real user input evidence once, replay it through the Harness,
  compare the same core chain after each risky change, and let Agents analyze
  the resulting evidence.
```

v1 must preserve the current project direction:

```text
Trace-first Recording + Post-hoc Skill Compilation
```

Harness should preserve facts and run controlled replay. It must not become a
contract-first recording layer, a site-specific selector rule engine, a second
planner, or a hidden place to fix RPA Agent bugs.

## Relationship To v0 And F003-F010

F003-F010 already introduced the building blocks:

- governed scenario assets;
- candidate and golden asset pools;
- offline snapshot and compiler regression;
- Skill Replay E2E;
- Stateful SOP Capture-to-Skill regression;
- Assisted Asset Review and Promotion;
- review packets and promotion commands.

v1 should not fork these into separate product concepts. Instead, it should
present them as one lifecycle:

```text
capture asset
  -> review and promote asset
  -> scripted asset-driven execution
  -> report machine evidence
  -> Agent analyzes result
  -> human decides whether to fix code, update assets, or promote coverage
```

## Core Boundary

The v1 boundary is:

```text
Scripts execute.
Agents explain.
Humans govern.
```

### Scripts Execute

The default Harness execution path should be a script or CLI runner. It should
not depend on an outer Agent clicking through the RPA product UI or deciding
what to do next during the run.

This keeps the default profile stable, reproducible, and comparable across
commits.

### Agents Explain

Agents are valuable after facts exist. They can read `review.md`, JSON reports,
logs, traces, snapshots, and generated Skills to summarize what happened,
compare changes, and suggest likely owner modules.

Agents may also help a human interpret whether an asset deserves promotion, but
they should not be the source of truth for changing asset state.

### Humans Govern

Humans confirm asset meaning, sensitivity, expected signals, and long-term
promotion. Promotion commands may be initiated by an Agent, but the governance
decision for blocking `candidate` or `golden` status should be human-approved.

## Primary User Journey

The intended v1 workflow is:

1. A user records a Full SOP or selected-step Harness asset.
2. The new asset starts as `draft` and remains local by default.
3. Harness stores checkpoint evidence: page state, DOM/HTML, trace events,
   runtime result, expected-signal draft, logs, and optional snapshots.
4. The user or Agent runs Assisted Asset Review to generate `review.md`.
5. The user reads `review.md` instead of reading raw capture files directly.
6. If the asset is useful, the user promotes it through CLI-backed governance.
7. Later RPA core-chain changes run Harness profiles over governed assets.
8. Harness writes machine-readable JSON and human-readable summary output.
9. An Agent analyzes the output and explains whether behavior improved,
   regressed, stayed equivalent, or lacks enough evidence.
10. The owning RPA component is fixed when a regression is real, then the same
    assets are rerun to verify the fix.

## Asset Lifecycle

v1 should use this lifecycle:

```text
draft -> candidate-lite -> candidate -> golden
```

### draft

`draft` is the default state for newly captured assets. Draft assets preserve
facts but are not trusted regression assets yet.

Draft assets:

- are local by default;
- may contain sensitive data;
- may have incomplete or unreviewed expected signals;
- should not block regression;
- should first receive a review packet.

### candidate-lite

`candidate-lite` is a non-blocking observation level. It is useful when an asset
looks promising but has not yet earned blocking status.

Candidate-lite assets:

- may run through validation, snapshot, compiler, Skill Replay, and Stateful
  SOP checks;
- should produce warnings instead of blocking failures;
- should not pollute the blocking baseline;
- do not imply sensitivity or expected-signal review is complete.

### candidate

`candidate` is a human-confirmed regression asset. It represents a real scenario
worth keeping in the default governed asset pool.

Candidate assets:

- have reviewed scenario meaning;
- have reviewed sensitivity;
- have reviewed expected signals;
- can participate in default blocking regression;
- are allowed to represent realistic messy page shapes, not just perfect
  examples.

### golden

`golden` is a smaller, more stable contract asset set. It should represent
long-term core capabilities and high-confidence regression contracts.

Golden assets:

- are promoted from candidate by human approval;
- should be stable, representative, and low maintenance;
- should not depend on live page state, random data, private login state, or
  accidental text;
- should be few enough that failures are meaningful.

Promotion from `candidate` to `golden` should be a human-approved contract
promotion. Agents may recommend promotion and scripts may run eligibility
checks, but Agents should not automatically decide golden status.

## Review And Promotion

Assisted Asset Review and Promotion should be split conceptually into two
layers.

### Scripted Review Packet

The scripted layer should generate factual review material from asset contents.
It should be stable and reproducible.

It may include:

- scenario identity;
- human SOP summary;
- page transitions;
- step intents and trace evidence;
- final observed outputs;
- expected-signal draft;
- asset validation results;
- snapshot, compiler, Skill Replay, and Stateful SOP observations;
- sensitivity and promotion questions.

This layer should not require live URL access and should not call an outer Agent
as an oracle.

### Agent-Assisted Interpretation

The Agent-assisted layer may turn the review packet and asset evidence into a
more readable explanation, risk summary, or promotion recommendation.

This is advisory. The authoritative state change should still happen through a
promotion CLI or equivalent deterministic command.

## Execution Profiles

v1 should expose one mental model with at least two execution profiles.

### Deterministic Profile

The deterministic profile is the default pre-submit evidence path for RPA
core-chain changes.

It should use captured assets and controlled inputs without asking the real
Planner/LLM to make new semantic decisions during the run.

Typical chain:

```text
captured asset
  -> captured HTML / historical trace / expected signals
  -> asset validation
  -> snapshot regression
  -> compiler regression
  -> generated Skill
  -> controlled Skill replay
  -> report
```

This profile is process-required before PR/readiness claims for RPA core-chain
changes, but it is not yet technically enforced by CI. Developers or Agents
should run it manually and record the result in Evidence, PR notes, or closeout
until the runner is stable enough to become a blocking PR check.

Future CI enforcement should wait until:

- the runner is fast enough;
- governed assets are reviewed and stable;
- asset sensitivity policy is clear;
- report output is reliable enough to debug failures;
- failure categories are actionable without live environment assumptions.

### Full/Live Profile

The full/live profile is a higher-fidelity validation mode. It still should not
use live websites as the source of truth. It should use controlled fixtures or
captured page states, but it may trigger the real RPA intelligent path.

Typical chain:

```text
controlled fixture or captured state
  -> scripted user input boundary
  -> RecordingRuntimeAgent / Planner / LLM
  -> new accepted trace
  -> compiler
  -> generated Skill
  -> controlled replay
  -> report
```

This profile is for:

- intranet validation;
- major RPA Agent changes;
- Planner/LLM behavior changes;
- natural-language step validation;
- iframe, region, dynamic list, modal, or form scenarios that need a more
  realistic recording simulation;
- periodic capability checks.

It should not be the default blocking pre-submit profile because model behavior,
planner output, and browser timing can add noise that makes ordinary commits
harder to compare.

## User Input Boundary

Harness v1 should model user input as a boundary that can be scripted from
assets. The input boundary may include:

- manual clicks;
- fills and keyboard input;
- navigation;
- natural-language recording instructions;
- selected regions;
- iframe context;
- popup or tab context;
- file downloads or uploads when represented by controlled fixtures;
- before/after page state.

For the RPA Agent internals, a Harness-driven run should be as close as possible
to a normal recording session. The difference should live at the outer input
boundary:

```text
Human path:
  human acts or describes intent
  -> RPA recording path
  -> accepted trace
  -> Skill compilation

Harness path:
  asset scripts equivalent input facts
  -> RPA recording path where the selected profile requires it
  -> accepted trace or historical trace evidence
  -> Skill compilation
```

## Region Selection

Region selection is not a special architecture track. It is one kind of user
input context.

v1 should treat selected regions the same way it treats clicks, fills, natural
language, iframe context, and list selection: as facts captured at the user
input boundary and consumed by snapshot, planner, trace, compiler, and replay
checks.

Expected signals may require that region semantics are preserved, but the
Harness should not grow region-specific branches where the generic user-input
context model is enough.

## Bug Analysis Boundary

Bug analysis is an important side benefit, not an independent Harness product.

Harness should preserve analysis-ready evidence:

- captured DOM/HTML;
- checkpoint JSON;
- raw and compact snapshots when available;
- trace events;
- runtime logs;
- compiler input and output;
- generated Skill;
- replay output and failure category.

Harness should not implement a heavy diagnostic engine. If a recording,
generated script, or replay fails, an Agent can analyze the preserved evidence.
The Harness should make the failure reproducible and comparable; the owning RPA
module should fix the bug.

This avoids turning Harness into a second RPA Agent or a rule-driven repair
system.

## Reports

Harness reports should have two layers:

- machine-readable JSON for Agents and repeatable comparison;
- concise human-readable Markdown or summary output for review and closeout.

Reports should answer:

- which assets ran;
- which assets were excluded and why;
- which profile ran;
- which runner failed first;
- whether the failure is blocking or warning-only;
- which page patterns or asset classes were affected;
- which generated outputs changed;
- whether the result suggests regression, improvement, no meaningful change, or
  insufficient evidence.

Reports should not overclaim global RPA health. Passing a small asset set means
that the covered core-chain paths stayed healthy for those assets.

## Non-goals

v1 should not:

- build a separate automatic bug diagnosis platform;
- let an outer Agent drive the default regression run by clicking through the
  RPA product UI;
- use live URLs as the correctness oracle;
- restore direct Agent chat as the golden runner;
- hide planner, snapshot, compiler, or replay bugs inside Harness-specific
  rules;
- promote assets to blocking `candidate` or `golden` without human review;
- make selected region behavior a special-case architecture track;
- enforce CI blocking before the deterministic profile is stable enough.

## Implementation Sequencing

The design can be recorded on `codex/rpa-harness-region-integration`, where
F003-F010 currently live.

Code implementation should wait until the active region-selection work is
merged into `upstream/master`, then the Harness branch should be rebased or
merged onto the new upstream baseline. This avoids building v1 execution logic
on an old region-selection and compiler context.

Recommended sequence:

1. Record this v1 design.
2. Wait for the current region-selection PR to land.
3. Update the Harness branch onto the latest `upstream/master`.
4. Create or update the owning Harness Feature for v1 implementation.
5. Implement the smallest slice that exposes one unified command or report
   shape for deterministic asset-driven execution.
6. Only after that consider full/live profile expansion.

## Acceptance Shape

Harness v1 is successful when a developer can say:

```text
I changed an RPA core-chain component.
I ran the deterministic asset profile.
The report shows which governed assets passed or failed.
An Agent can explain the report from stored evidence.
If an asset should become more trusted, a human can promote it through CLI-backed
governance.
If the change touches Planner/LLM behavior, I can additionally run the full/live
profile against controlled fixtures.
```

The system should feel boring in the best way: repeatable enough to trust,
evidence-rich enough for Agent analysis, and small enough that Harness does not
become its own competing RPA product.
