# RPA Golden Evaluation Vision

## Purpose

This document defines the product-level evaluation vision for RPA Harness work.
It is the shared north star for F003 and later Harness features, not a
feature-local note.

The goal is to turn one-off RPA recording sessions into reusable, explainable,
and comparable engineering assets. Those assets should let the team evaluate
core-chain changes without guessing whether a fix for one page has regressed
another page shape.

## Original Problem

The RPA Agent project translates SOP intent into executable Skills through a
core chain that includes recording, page evidence, DOM snapshot generation,
trace normalization, Skill compilation, and replay.

Before Harness, the project could discover page-specific failures, but it could
not reliably answer:

- Which real page shapes have already been encountered?
- Which HTML and step intent produced a past bug?
- Did a DOM snapshot compression change preserve task-critical facts?
- Did a compiler change hard-code a recording-time value?
- Did a fix improve one scenario while degrading another?
- Which scenarios are covered by durable regression assets?

## Golden Evaluation Definition

An RPA golden evaluation is not just a live task prompt and a pass/fail result.
It is a reusable scenario asset plus one or more standard execution modes.

A golden scenario asset should preserve enough factual context to support both
analysis and regression:

- source URL as provenance and optional refresh target
- captured HTML checkpoints
- SOP intent and step intent
- manual or natural-language step type
- before and after page state
- trace events and runtime outputs
- raw and compact snapshot baselines when available
- compiler input and compiler output baselines when available
- expected signals for snapshot, compiler, replay, and final result checks
- scenario tags and page-pattern coverage
- quality, sensitivity, and promotion status

The asset is the durable unit. Runners are different ways to consume that unit.

## Primary Execution Modes

### Offline Core-Chain Regression

Offline regression is the default Harness mode for risky core-chain changes.
It uses captured assets without reopening the live website.

Typical checks:

- HTML to raw snapshot
- raw snapshot to compact snapshot
- intent plus snapshot to action or trace analysis
- trace to compiler input
- compiler input to Skill output
- current output compared with expected signals and baselines

This mode is fast, deterministic, and suitable for frequent local or CI use. It
does not prove the entire business task succeeds, but it does expose whether the
core chain still preserves and transforms the facts captured in real scenarios.

### Stateful SOP Capture-to-Skill Regression

Stateful SOP Capture-to-Skill Regression is the target mode for simulating the
real recording product path without requiring a human to operate the product UI
during every evaluation run.

The goal is internal equivalence:

```text
Human recording path:
  human opens pages / clicks / describes intent
  -> RPA Agent captures trace
  -> TraceSkillCompiler generates Skill

Harness replay path:
  governed scenario asset provides captured URL / HTML / step intent / actions
  -> RPA Agent receives equivalent recording inputs
  -> RPA Agent captures trace
  -> TraceSkillCompiler generates Skill
```

For the RPA Agent core, the Harness-driven path should be as indistinguishable
as possible from a normal recording session. The difference should live at the
outer input boundary: pages and user actions come from captured scenario
assets instead of live human interaction. The inner product chain should still
exercise recording session state, accepted trace generation, trace
normalization, compiler input, Skill compilation, and optional Skill replay.

This mode exists because Live Agent E2E is too noisy as the foundation, while
plain Skill Replay E2E starts too late in the chain. Stateful
Capture-to-Skill regression should answer whether historical captured assets
can drive the same internal RPA recording pipeline that real users trigger.

Typical checks:

- session starts with a controlled scenario asset provider
- each SOP step advances through captured page state and recorded intent
- manual steps preserve action type, locator evidence, URL transition, and
  trace events
- natural-language steps preserve user intent and runtime result evidence
- accepted trace count, ordering, step type, output keys, and expected signals
  match the governed asset
- `TraceSkillCompiler` compiles the resulting accepted trace
- generated Skill can optionally be replayed against controlled HTML or a
  controlled business page

### Skill Replay E2E

Skill Replay E2E is the main end-to-end direction for golden evaluation.

It should compile a captured SOP or trace into a Skill, execute the Skill in a
controlled replay environment, and compare the final result with expected
signals.

The replay target may be:

- a fixture page created from captured external HTML
- a controlled local business application page
- a replayable page served by an evaluation service

This mode is closer to the real product path than direct Agent chat because it
tests the SOP to trace to Skill to replay chain.

Skill Replay E2E remains valuable, but it is downstream of
Capture-to-Skill regression. It proves that generated Skills can run; it does
not by itself prove that the recording-time SOP capture path still produces the
right trace evidence.

### Live Agent E2E

Live Agent E2E means asking an agent to operate the RPA Agent product UI the way
a human would: start recording, operate a browser, describe or record SOP steps,
compile a Skill, and test it.

This is not the current primary path. It is too expensive and unstable to serve
as the golden evaluation foundation because failures can come from nested UI
automation, model variance, product UI state, browser timing, target page state,
or the RPA core chain itself.

Live Agent E2E may be useful later as a smoke or demo layer, but it must not
replace Offline Core-Chain Regression or Skill Replay E2E as the Harness
correctness oracle.

## Relationship To `rpa-eval-app`

`rpa-eval-app` remains valuable, but its current runner is not the golden
evaluation main path.

The useful part of `rpa-eval-app` is the controlled business application:

- stable procurement, supplier, contract, approval, and report pages
- resettable backend fixtures
- business-state assertion APIs
- downloadable artifacts and audit events

The current runner directly calls Agent chat against the live eval app. That
can measure online task completion, but it does not prove the real SOP to Skill
path:

```text
SOP intent -> captured step evidence -> trace -> Skill compilation -> replay
```

Therefore `rpa-eval-app` should be treated as a scenario/page provider and
assertion provider for future Skill Replay E2E, not as the primary golden
runner itself.

## Harness Boundary

RPA Harness should capture facts, preserve assets, and provide regression
judgment.

It should not silently become:

- a site-specific selector rule engine
- a replacement for planner semantic understanding
- a business extraction fix hidden inside evaluation code
- a live crawler whose current URL state is the source of truth
- a runner that only proves the model can complete one online task today

When a Harness asset exposes a problem such as a hard-coded compiler literal,
the Harness outcome is to make the failure reproducible and comparable. The
business or compiler fix should happen in the owning RPA component and then be
validated against the asset set.

## F003 Direction

F003 should use this vision to define the Golden Scenario Asset Model.

The immediate objective is to promote captured Harness data from "files in a
capture directory" into governed scenario assets that can support:

- Offline Core-Chain Regression
- future Skill Replay E2E
- abnormal-case analysis
- scenario and page-pattern coverage reporting

F003 should not restart from the existing direct Agent chat runner. It should
reuse the good ideas from that runner, such as case ids, tags, expected
signals, assertions, and reports, while changing the execution foundation to
captured assets.

## F009 Direction

F009 should treat Stateful SOP Capture-to-Skill Regression as the next coherent
capability target after F008.

The immediate objective should be to use one governed Full SOP asset as a
stateful scenario provider that can drive the recording/trace/compiler path
without live human UI operation. The runner should simulate the recording input
boundary, not bypass the product core by compiling existing trace files only.

F009 should not:

- expand the candidate asset set as part of feature implementation
- restore direct Agent chat as the oracle
- require live external websites as the source of truth
- implement a nested agent that clicks through the RPA product UI
- hide planner, compiler, or extraction bugs inside Harness-specific fixes

## Success Shape

The Harness program is on track when core-chain changes can be evaluated by
asking:

- Which golden assets passed or failed?
- Which page patterns were affected?
- Which runner mode exposed the change?
- Did the historical asset drive the same internal recording-to-Skill path that
  a real user would have triggered?
- Did the output improve, degrade, or intentionally change?
- Is this a Harness capture/asset issue or an RPA Agent component issue?

The desired development shift is:

```text
Before: fix a page bug and hope other pages still work.
After: change a core chain, run golden assets, see the affected scenarios, and
       promote new page shapes into long-term knowledge.
```
