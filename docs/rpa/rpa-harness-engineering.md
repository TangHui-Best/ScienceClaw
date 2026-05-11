---
doc_kind: spec
status: active
created: 2026-05-11
updated: 2026-05-11
owner: rpa
scope: rpa-harness
feature_ids: [F001]
references:
  - docs/rpa/trace-first-architecture.md
  - docs/rpa/failure-repair-policy.md
  - docs/rpa/trace-skill-compiler-generalization.md
---

# RPA Harness Engineering

## Document Status

This document is the active design guideline for RPA harness engineering. It
defines the target harness architecture and rollout order, but it does not
override source code, `AGENTS.md`, or the trace-first RPA architecture rules.

If this document conflicts with current runtime behavior, treat the conflict as
an implementation gap or a spec update candidate. Do not silently change the RPA
main path to satisfy the harness document.

## Purpose

RPA harness engineering exists to turn real RPA failures into durable engineering
assets. Its goal is not to add more generic tests. Its goal is to make the RPA
development loop observable, reproducible, attributable, and resistant to
regression.

The harness should answer these questions:

- What exactly happened during recording, repair, compilation, and replay?
- Did the raw snapshot contain the needed facts?
- Did the compact snapshot preserve the facts needed by the task?
- Did the planner fail because of missing evidence, wrong judgment, or bad code?
- Did the compiler generalize the trace, or did it freeze recording-time values?
- Did a fix for one RPA case break another historical case?

The core loop is:

```text
real failure -> fact packet -> offline reproduction -> layered attribution -> harness case -> regression guard
```

The long-term purpose is to move RPA work from ad hoc bug fixing to cumulative
system learning.

## Scope

This document covers harness engineering for the trace-first RPA system:

- recording-time natural language and manual actions
- raw and compact snapshot generation
- DOM structure compression
- repair evidence and repair boundaries
- trace-to-skill compilation
- replay validation
- selected end-to-end scenarios

Existing historical golden-eval work should not be treated as the baseline for
this harness if its flow differs from the real user flow. It may be used later
as reference material, but the first harness corpus must come from real
recording, real failure packets, real snapshots, and real trace compilation
outputs.

## Design Principles

### Facts Before Judgment

The system should preserve factual evidence before deciding what to fix.
Relevant facts include the user instruction, URL, title, raw snapshot, compact
snapshot, generated code, execution result, raw error, repair input, repair
output, accepted trace, and compiled script.

Do not start with prompt changes, selector rules, or site-specific patches when
the failure layer is still unknown.

### Real Flow Before Ideal Flow

Harness cases should model the real RPA flow:

```text
record -> trace -> compile -> configure -> replay -> diagnose
```

Avoid using artificial shortcuts as the primary baseline. A harness that passes
but does not reflect real user behavior creates false confidence.

### Samples Before Rules

When a failure reveals a general page structure or trace pattern, preserve it as
a case before adding broad rules. The harness corpus is the system's memory.

### Assertions Before Scale

The first harness version should prefer a small number of high-value assertions
over a large number of unstable end-to-end flows. Useful assertions identify a
layer of failure, not only pass or fail.

### Offline Evaluation Before Online Intervention

The production path should emit facts. The harness path should evaluate facts.

```text
Production path emits facts.
Harness path evaluates facts.
```

Harness evaluators must not take over the recording planner, repair loop, or
compiler behavior at runtime.

### Domain Harness Before Generic Observability Platforms

OpenTelemetry, Langfuse, Phoenix, or other observability tools may be added
later as optional adapters after license review. They should not be part of the
first harness core. The first harness core should be local, file-based,
versionable, and specific to RPA failure modes.

## Production Boundary

Harness evaluation is primarily for development, CI, and offline diagnosis.
Production should only perform low-cost fact capture.

Production may:

- save a failure packet when a recording step, repair, compilation, or replay
  fails
- save raw and compact snapshot references when diagnostics are enabled or a
  failure occurs
- save accepted traces, generated code, execution result, and diagnostics
- redact sensitive values before writing artifacts
- enforce retention limits to protect endpoint disk usage

Production must not:

- run the full harness evaluator suite
- perform heavy raw-vs-compact diffs in the user path
- block non-dangerous RPA actions because a harness assertion would fail
- add multiple repair rounds
- turn experience hints into online planner rules
- return to contract-first recording for harness convenience

Safety checks remain separate from harness checks. Destructive shell access,
sensitive local paths, infinite loops, and other safety risks may still be
blocked before execution. Selector fragility, empty extraction, slow navigation,
or weak snapshot evidence should be diagnosed through facts and repair, not
pre-execution blocking.

## Core Artifacts

### ObservationPacket

An observation packet records facts for a successful or partially successful
stage.

Suggested fields:

```text
packet_id
session_id
step_id
stage
user_instruction
started_at
ended_at
before_page
after_page
raw_snapshot_ref
compact_snapshot_ref
accepted_trace_ref
generated_code_ref
execution_result
diagnostics
compiler_output_ref
metadata
```

Stages may include:

```text
recording
snapshot
planner
execution
repair
compile
replay
```

### FailurePacket

A failure packet records the facts needed for offline replay and attribution.

Suggested fields:

```text
packet_id
session_id
step_id
stage
failure_type
user_instruction
current_url
current_title
failed_plan_summary
failed_code_ref
raw_error_ref
snapshot_after_failure_ref
compact_snapshot_ref
repair_input_ref
repair_output_ref
attempt_trace_ref
accepted_trace_ref
metadata
```

Failure packets should be produced on failure or explicit diagnostic capture,
not for every successful user action by default.

### Case Metadata

Every harness case should explain why it exists.

Suggested fields:

```text
case_id
case_type
title
source
created_at
related_files
historical_failure
task_shape
input_refs
expected_properties
forbidden_properties
attribution_layer
notes
```

`source` should identify whether the case came from a real failure packet,
manual diagnostic capture, sanitized production artifact, or a later curated
fixture.

## Case Repository

The harness case repository should live outside the production RPA modules.

Recommended layout:

```text
tests/rpa_harness/
  cases/
    dom_morphology/
    snapshot/
    compiler/
    repair/
    scenario/
  evaluators/
  runners/
  reports/
```

The repository should keep stable case metadata under version control. Large or
sensitive artifacts should use a controlled artifact directory with redaction
and retention rules.

## Packet-To-Case Promotion

Failure packets are raw evidence. They are not automatically harness cases.

A failure packet should be promoted to a harness case only when it exposes a
reusable system behavior:

- a DOM structure shape the compressor should learn or preserve
- a raw-vs-compact evidence loss pattern
- a compiler generalization boundary
- a repair evidence or policy boundary
- a real SOP scenario that protects a high-value user flow

Do not promote packets only because they are recent, noisy, or easy to capture.
Do not promote site-specific details unless they reveal a general structural
shape or RPA boundary. The promotion step should produce case metadata,
redacted artifacts, expected properties, forbidden properties, and an attribution
layer.

This gate prevents production diagnostics from becoming an unbounded corpus and
keeps endpoint disk usage separate from curated harness knowledge.

## DOM Morphology Corpus

The DOM morphology corpus is a first-class part of the harness. It captures page
structure patterns that affect snapshot compression quality.

This corpus is not organized by website. It is organized by structural shape.

Examples:

- key and value are split across separate sibling divs
- label is on one line and value is on the next line
- field value is inside a display-only component wrapper
- table header and cells have no explicit DOM association
- card/list candidates have title, description, metadata, and action split
  across multiple nodes
- virtualized tables only render visible rows
- iframe contains the primary content
- placeholder has semantic meaning but label is missing
- button text is unstable but aria-label is stable
- candidate cards require horizontal comparison rather than top-K region
  expansion

Each DOM morphology case should state:

```text
HTML or raw snapshot shape
task_shape
facts expected in raw_snapshot
facts expected in compact_snapshot
expected semantic view
expected locator preservation
failure mode guarded by the case
```

Task shapes should include at least:

```text
detail_extraction
form_fill
table_extraction
candidate_selection
search_result_selection
navigation_action
```

This corpus directly supports the evolution of `snapshot_compression.py`.

## Evaluators

### DomMorphologyEvaluator

Checks whether known DOM structure shapes become useful semantic views.

It should verify:

- label/value pairs are recovered when split across nearby nodes
- table structure preserves headers, rows, and row-level actions
- candidate collections preserve comparable titles, descriptions, metadata, and
  primary action locators
- form views preserve visible editable fields and meaningful labels
- iframe content keeps frame context

### SnapshotEvaluator

Compares raw and compact snapshots for task-relevant information.

It should verify:

- facts present in raw snapshot are not lost in compact snapshot
- candidate selection tasks preserve a horizontal candidate set
- detail extraction tasks preserve relevant field/value evidence
- table tasks preserve row and column relationships
- action locators needed by the task remain available
- failures identify whether the root cause is raw evidence absence or compact
  evidence loss

This evaluator enforces the rule: compare raw and compact snapshots before
repairing planner prompts.

### CompilerEvaluator

Checks whether accepted traces are compiled into generalized skill code.

It should verify:

- recording-time observed values are not hard-coded when a dynamic source exists
- `_results` and `output_key` references are used for cross-step dataflow
- semantic runtime AI steps remain runtime AI
- deterministic snapshot extraction compiles to Playwright only when safe
- stable URL suffixes may be inferred, but dynamic bases must remain dynamic
- empty outputs are not treated as non-empty contracts unless task intent says so
- site-specific helpers are not introduced as generic compiler behavior

### RepairEvaluator

Checks repair evidence and policy boundaries.

It should verify:

- repair input includes raw error facts, current URL/title, failed code or plan,
  and post-failure page state
- experience hints are advisory only
- repair does not exceed the configured single retry boundary
- safety risks remain distinct from stability issues
- repair failures preserve enough facts for later offline diagnosis

### ScenarioEvaluator

Runs a small number of high-value real user flows.

It should verify:

- real recording flows can produce accepted traces
- generated scripts can replay with intended parameters
- important outputs are present or intentionally empty
- failures produce useful failure packets

Scenario cases should be few, stable, and representative. They should not become
the only regression mechanism because they are slower and harder to attribute
than layer-specific cases.

## Runner Commands

Recommended command shape:

```powershell
python -m tests.rpa_harness.run dom
python -m tests.rpa_harness.run snapshot
python -m tests.rpa_harness.run compiler
python -m tests.rpa_harness.run repair
python -m tests.rpa_harness.run scenario
python -m tests.rpa_harness.run all
```

Each runner should output:

```text
case count
pass/fail summary
failed cases
attribution layer
important diff
artifact paths
```

The first version can be a CLI-only harness. A dashboard is not required.

## Reports

Recommended output layout:

```text
reports/rpa_harness/latest/
  summary.json
  dom_morphology_report.md
  snapshot_diff_report.md
  compiler_report.md
  repair_report.md
  scenario_report.md
```

Reports should optimize for diagnosis, not presentation. A useful report states:

- which capability regressed
- which real or curated case failed
- whether raw evidence was missing or compact evidence was lost
- whether failure belongs to snapshot, planner, code generation, repair,
  compiler, replay, or environment
- which artifacts to inspect next

## Build Order

Use agent batches and verifiable capability increments instead of natural time
plans.

### Batch 0: Fact Packet Schema

Define `ObservationPacket` and `FailurePacket` schemas. Specify redaction and
retention rules. Ensure production capture is disabled by default for successful
paths and enabled for failures or diagnostic mode.

Acceptance:

- packet schema exists
- one synthetic packet can be written and read
- sensitive fields have a documented redaction path

### Batch 1: Failure Capture Artifacts

Capture three to five recent real failures as sanitized failure packets.

Acceptance:

- packets can be inspected offline
- each packet identifies stage, failure type, raw error, and artifact refs
- endpoint disk usage remains bounded by retention policy

### Batch 2: DOM Morphology Harness

Create the first DOM morphology cases for key/value, table, candidate cards,
form fields, and iframe content.

Acceptance:

- evaluator can distinguish missing raw facts from compact loss
- at least five structural cases run locally
- each case documents its guarded failure mode

### Batch 3: Snapshot Diff Harness

Implement raw-vs-compact comparison for task-relevant facts.

Acceptance:

- candidate selection and detail extraction are treated differently
- reports identify facts lost during compression
- planner prompt changes are not the first response to compact evidence loss

### Batch 4: Compiler Harness

Implement compiler regression and generalization checks from real traces.

Acceptance:

- observed values are detected when hard-coded incorrectly
- dynamic `_results` references are required when dataflow is clear
- runtime AI preservation is checked for semantic steps
- URL base/suffix generalization is checked without site-specific logic

### Batch 5: Repair Harness

Implement repair packet evaluation.

Acceptance:

- repair input fact completeness is checked
- experience hints are confirmed advisory
- single-repair boundary is enforced

### Batch 6: Scenario Harness

Add a small set of real SOP smoke scenarios.

Acceptance:

- scenario failures emit failure packets
- scenario reports point to lower-layer artifacts
- scenarios do not replace layer-specific cases

### Batch 7: Optional Observability Adapters

Consider OpenTelemetry, Langfuse, Phoenix, or other adapters only after the
local harness data model is stable and licensing has been reviewed.

Acceptance:

- adapter is optional
- harness core has no hard dependency on the platform
- license impact is documented

## Success Criteria

The first useful harness version is successful when:

- real failures can be saved as failure packets and inspected offline
- at least five DOM structure shapes are represented as cases
- raw-vs-compact loss can be reported for snapshot changes
- compiler changes are guarded against known generalization regressions
- repair changes are checked for fact completeness and policy boundaries
- a small number of real SOP scenarios run as smoke coverage

## Non-Goals

The first harness version should not:

- build a large dashboard
- depend on Langfuse, Phoenix, or another platform as core infrastructure
- reuse historical golden-eval flows as the baseline when they diverge from real
  user flow
- treat captured failure packets as approved harness cases without triage
- introduce site-specific rule libraries
- add multiple repair rounds
- place harness evaluator decisions in the production main path
- make recording contract-first again

## Relationship To Existing RPA Rules

This harness supports the current trace-first architecture:

- recording remains factual and bounded
- compilation remains post-hoc
- repair remains fact-first and bounded
- snapshot compression remains task-shape aware
- site examples remain validation samples, not core abstractions

The harness is the offline learning and regression layer around those rules. It
should make the rules easier to enforce without changing the runtime ownership
boundaries.
