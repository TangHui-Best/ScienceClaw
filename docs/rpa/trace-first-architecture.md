# RPA Trace-first Architecture

## Purpose

The RPA recorder converts a user's SOP into a replayable Skill through a mixed workflow:

- Manual browser actions for precise operations.
- Natural-language commands for semantic, logical, or tedious operations.
- Post-hoc compilation for replayable, generalized Playwright scripts.

The core architecture is:

```text
Recording time: operate the browser and record factual traces.
Compilation time: generalize traces into replayable Skill code.
Replay time: run deterministic Playwright where possible, use runtime AI only for semantic steps.
```

## Why Trace-first

Previous Contract-first designs tried to infer a complete step contract during interactive recording. That made one user command trigger too much work: snapshot capture, planning, compiling, validating, repairing, and sometimes done checks. The result was slower and less predictable than direct recording.

Trace-first moves the heavy work out of the live recording path. During recording, success means the browser actually performed the current step and the system captured enough evidence to reason about it later.

## Recording Runtime Responsibilities

The recording runtime is intentionally small:

- Execute one current user instruction.
- Record the browser state before and after the step.
- Record the code/action that actually ran.
- Record structured output when data is extracted.
- Update runtime results for later steps.
- Keep failed attempts as diagnostics, not accepted timeline steps.

Natural-language commands are handled by `RecordingRuntimeAgent`. It may use one LLM call, plus at most one bounded repair call after execution failure.

## Post-hoc Skill Compilation Responsibilities

`TraceSkillCompiler` turns accepted traces into `skill.py`.

It should:

- Remove failed attempts from the replay path.
- Preserve trace order.
- Convert manual actions into Playwright operations.
- Convert deterministic AI traces into deterministic replay code when safe.
- Replace recording-time observed values with dynamic references when a prior trace produced the value.
- Preserve runtime AI only when semantic judgment is genuinely required.
- Add replay validation for important outputs.

It should not:

- Re-plan the whole SOP with LLM by default.
- Treat one recorded site as the architecture.
- Leak observed recording URLs or values into replay logic when a dynamic dependency exists.

## Runtime AI Boundary

Runtime AI is allowed when the step's result depends on semantic judgment over the current page, for example:

- "Open the project most related to Python."
- "Choose the most risky customer."
- "Summarize the current page."

Runtime AI is not the default for deterministic logic such as:

- Open a known URL.
- Navigate to a stable subpage of a previously selected object.
- Rank visible rows by a numeric field.
- Extract fixed fields from visible records.

## Trace Data Contract

Accepted traces should be factual records. They are not final abstractions.

A useful trace includes:

- User instruction or manual action summary.
- Source: manual or AI.
- Before and after page state.
- Locator candidates or generated Python Playwright code.
- Output key and structured output when available.
- Repair diagnostics when relevant.

Recording-time code may contain concrete values because it was written to operate the browser immediately. Compilation is responsible for deciding whether those values should be generalized.

## Design Guardrails

- Recording path must remain direct and bounded.
- Repair is bounded to one attempt unless the architecture is explicitly revisited.
- Python Playwright is the default generated scripting style.
- Free-form complex JavaScript is avoided in the recording loop.
- Failed attempts belong in diagnostics, not the primary trace timeline.
- Generalization happens after recording, where the compiler can see the full SOP context.

