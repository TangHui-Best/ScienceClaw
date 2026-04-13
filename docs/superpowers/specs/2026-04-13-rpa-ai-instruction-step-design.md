# RPA AI Instruction Step Design

## Background

The current RPA system already supports two ways to accumulate skill behavior:

1. Recorded UI actions, which become structured `RPAStep` entries.
2. AI assistant guidance, which either:
   - resolves to structured atomic actions such as `navigate`, `click`, `fill`, `extract_text`, `press`, or
   - falls back to an `ai_script` step containing generated Playwright code.

This works well for:

- precise UI operations
- fixed multi-step procedures
- complex but still pre-compilable browser logic

It does **not** preserve rule semantics that must be reinterpreted at runtime.

Example:

- "Fill form B from table A by matching rows on name and then submit"

Today, the assistant will translate that request into either:

- a sequence of fixed steps, or
- one `ai_script` code blob

In both cases, the generated skill preserves the compiled execution path, not the original semantic rule. That causes poor generalization when runtime data or page meaning changes while the overall intent remains the same.

## Problem Statement

The current system lacks a step type that preserves **runtime semantic logic**.

The gap is not "AI chat is missing". AI chat already exists.

The real gap is:

- structured steps preserve actions
- `ai_script` preserves compiled code
- neither preserves a rule that must be re-understood when the skill executes later

We need a third step type, `ai_instruction`, to represent:

- logic-bearing semantic steps
- whose correctness depends on runtime understanding of the current page/context
- and which should be executed by runtime AI planning rather than by replaying precompiled code

## Design Goals

1. Preserve rule semantics inside the recorded skill.
2. Reuse existing structured action execution where possible.
3. Keep phase-1 safe and controllable.
4. Keep the design evolvable so future expansions do not require a rewrite.

## Non-Goals

1. Replace structured steps.
2. Replace `ai_script`.
3. Introduce unrestricted runtime Python generation in phase 1.
4. Turn every "complex" action into AI execution.

## Step-Type Boundary

### Structured Step

Use when the action can be represented as an existing atomic operation and does not need new semantic understanding at execution time.

Examples:

- click submit
- fill username
- extract title text
- click the first visible result

Core property:

- action-oriented, not rule-oriented

### ai_script

Use when the action cannot be represented cleanly as an existing atomic step, but can still be safely compiled into deterministic Playwright code at generation time without losing its essential meaning.

Examples:

- fixed loops over known DOM structures
- fixed conditional branches
- fixed cross-page transfers with stable field mapping

Core property:

- complex execution flow, but still pre-compilable

### ai_instruction

Use only when compiling the logic into a fixed script would lose its core value because the step must re-interpret runtime semantics.

Examples:

- match data from table A to form B using semantic name correspondence
- choose the business path based on the current page meaning
- find the most relevant/latest/closest item by semantic intent, not fixed structure
- runtime semantic mapping across changing page structures

Core property:

- rule-oriented, not merely action-oriented

## Decision Rule

When the assistant generates a step, it must decide in this order:

1. Can this be expressed as an existing structured atomic step?
   - yes -> structured step
2. If not, can it be safely compiled to fixed Playwright logic without losing essential semantics?
   - yes -> `ai_script`
3. If compiling it would lose runtime semantic value:
   - use `ai_instruction`

## Data Model

Phase-1 introduces a new `RPAStep.action` value:

- `ai_instruction`

Minimal step shape:

```json
{
  "action": "ai_instruction",
  "source": "ai",
  "description": "Sync data from table A into table B by matching rows on name and submit",
  "prompt": "Fill table B from table A by matching rows on name, then submit",
  "instruction_kind": "semantic_rule",
  "input_scope": {
    "mode": "current_page"
  },
  "output_expectation": {
    "mode": "act"
  },
  "execution_hint": {
    "requires_dom_snapshot": true,
    "allow_navigation": true,
    "max_reasoning_steps": 10
  },
  "result_key": null,
  "sensitive": false
}
```

### Field Semantics

- `prompt`
  - the canonical semantic rule that must survive into skill execution
- `instruction_kind`
  - lightweight classification for runtime policy and future expansion
- `input_scope`
  - describes what context runtime planning may consume
- `output_expectation`
  - whether the step is expected to act, extract, or both
- `execution_hint`
  - runtime policy hints, not persisted execution result

## Evolvability Principle

Phase-1 restrictions are **policy restrictions**, not **model restrictions**.

That means:

- the schema must support future growth
- phase-1 only enables a safe subset

### Example

Phase-1:

```json
{
  "input_scope": { "mode": "current_page" }
}
```

Future:

```json
{
  "input_scope": {
    "mode": "multi_source",
    "sources": ["current_page", "history_steps", "artifacts"]
  }
}
```

This should be an additive evolution, not a refactor.

## Runtime Architecture

The implementation should be split into three layers.

### 1. Step Description Layer

Responsibility:

- persist semantic intent inside the recorded skill

Owned fields:

- `prompt`
- `instruction_kind`
- `input_scope`
- `output_expectation`
- `execution_hint`

This layer should remain stable.

### 2. Runtime Planning Layer

Responsibility:

- convert an `ai_instruction` step into an executable runtime plan

Phase-1 plan format:

```json
{
  "plan_type": "structured",
  "actions": [
    {
      "action": "click",
      "target_hint": { "role": "button", "name": "Submit" }
    }
  ]
}
```

Future expansion:

- `plan_type = code`
- `plan_type = hybrid`

The architecture must allow these later, but phase-1 only enables `structured`.

### 3. Runtime Execution Layer

Responsibility:

- execute the runtime plan against the active page/context

Phase-1:

- only executes structured atomic actions
- reuses existing assistant-runtime primitives
- enforces bounded reasoning

## Phase-1 Runtime Policy

These are initial execution policies, not permanent architectural constraints:

- `input_scope.mode = current_page` only
- `plan_type = structured` only
- `max_reasoning_steps = 10`
- bounded runtime loop
- failure surfaces clearly instead of silently degrading to `ai_script`

## Generator Behavior

`generator.py` must add a dedicated branch for `ai_instruction`.

Instead of expanding it into fixed Playwright operations directly, generated skill code should call a runtime helper, conceptually:

```python
await execute_ai_instruction(
    current_page,
    instruction=step_payload,
    results=_results,
    tabs=tabs,
)
```

The generator should stay declarative:

- it serializes the instruction payload
- it does not embed the runtime AI planning algorithm inline

## Runtime Helper Behavior

Introduce a runtime helper module dedicated to `ai_instruction`.

Responsibilities:

1. Read the instruction payload.
2. Build the permitted runtime context from `input_scope`.
3. Produce a bounded runtime plan through AI reasoning.
4. Require `plan_type = structured` in phase 1.
5. Execute the returned atomic actions using existing runtime execution utilities.
6. Write extracted values into `_results` when `output_expectation` requires it.
7. Return structured logs/errors.

## Why Not Reuse ai_script

`ai_script` remains useful, but it is not sufficient for this feature.

`ai_script` is:

- compile-time AI
- runtime fixed code

`ai_instruction` is:

- runtime AI
- runtime semantic reinterpretation

That distinction is the whole reason the new step type exists.

## Failure Policy

Phase-1 failure handling should be explicit:

- if planning fails, fail the step
- if structured execution fails, fail the step
- do not silently downgrade to `ai_script`
- expose enough logs for debugging and later UI surfacing

This keeps boundaries honest during rollout.

## Testing Strategy

### Unit Tests

1. assistant step classification:
   - structured vs `ai_script` vs `ai_instruction`
2. generator:
   - `ai_instruction` emits runtime helper call, not fixed Playwright expansion
3. runtime helper:
   - accepts valid instruction payload
   - rejects unsupported phase-1 scopes/plan types
   - enforces `max_reasoning_steps = 10`

### Integration Tests

Representative semantic case:

- "Fill table B from table A by matching rows on name, then submit"

Expected:

- recording stores `ai_instruction`
- generated skill preserves the semantic rule payload
- execution invokes runtime helper rather than replaying a precompiled action sequence

## Open Expansion Path

After phase-1 stabilizes, additive evolution can include:

- additional `input_scope` modes
- `plan_type = code`
- hybrid plans
- multi-page/runtime artifact context
- richer `instruction_kind`
- policy-based step budgets and model selection

## Final Summary

The correct direction is not "put more AI code into generated scripts".

The correct direction is:

- add a third step type, `ai_instruction`
- preserve semantic rules as first-class runtime steps
- keep structured steps for actions
- keep `ai_script` for fixed compiled complexity
- let runtime AI planning exist as a bounded, reusable execution layer

This gives the system a clean and evolvable separation:

- structured step = action
- `ai_script` = compiled code
- `ai_instruction` = runtime semantic rule
