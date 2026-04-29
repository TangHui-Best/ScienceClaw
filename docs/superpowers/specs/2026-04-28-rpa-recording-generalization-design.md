# RPA Recording Generalization Design

## Goal

Improve RpaClaw's AI recording path so generated traces and exported scripts remain reliable when runtime business data changes, without adding eval-case-specific rules or site templates.

## Constraints

- Keep the recording path trace-first: execute real browser operations and record observable traces.
- Do not add hard-coded knowledge of the current eval cases, fixed IDs, or app-specific flows.
- Separate stable UI anchors from dynamic business data.
- Treat Playwright errors and current page state as authoritative repair facts.
- Preserve existing skill export behavior unless richer trace metadata is present.

## Reference Model

Playwright should remain the execution substrate. Use locator contracts that re-resolve at action time: role, label, placeholder, test id, scoped table/form locators, and assertions/postconditions. Avoid persisting ordinal or business-value selectors unless the user explicitly asked for an ordinal target.

Browser-use's useful pattern is the observe/action/result loop: compact page state is shown to the model, the model emits a structured action, a deterministic controller executes the action, and the result is fed back to the next step. RpaClaw should adopt the structure without replacing trace-first recording with a heavy contract layer.

## Data Model

Classify values observed during recording:

- `ui_anchor`: Stable UI contract such as label text, role/name, test id, section title, table headers, dialog title.
- `user_param`: Value supplied or implied by the user's command, such as contract number, target record number, item quantity, unit price.
- `derived_data`: Data read from the page and reused later, such as supplier number or department.
- `runtime_output`: Data created by the application, such as submitted request numbers, generated order numbers, download names.

Only `ui_anchor` values are safe to embed directly in exported locators. Dynamic data must be represented as input bindings, previous output bindings, or runtime assertions.

## Runtime Plan Parsing

The planner output should be parsed as a structured JSON object even when the model adds surrounding text. The parser should:

- Prefer fenced JSON content.
- Fall back to the first complete JSON object with `JSONDecoder.raw_decode`.
- Normalize core fields exactly once.
- Preserve extra text only for diagnostics.
- Reject malformed plans with a clear error that includes a short raw-output excerpt.

## Snapshot Extraction

`extract_snapshot` should support both canonical field lists and planner-friendly maps:

- Canonical: `fields: [{"label": "合同编号", "value": "CT-..."}]`
- Compatible: `fields: {"合同编号": "CT-..."}`

Execution should convert both into a normalized field list and keep signal metadata usable by the compiler.

## Effect Verification

`expected_effect=mixed` must not mean URL navigation. The verifier should accept browser-visible evidence from:

- URL change or explicit target URL.
- `effect.action_performed`.
- Non-empty structured output for action plans.
- Download signals.
- Postcondition metadata when supplied by planner or deterministic overlay.

When no direct evidence exists, the verifier may fail, but the error should explain that no postcondition/action evidence was observed rather than requiring navigation.

Before repair, the runtime should prefer "already achieved" evidence when available. A successful output or postcondition must not be turned into a repair attempt just because a SPA URL did not change.

## Dynamic Binding Metadata

Accepted traces may carry optional metadata:

- `input_bindings`: named dynamic inputs with source, default, and value classification.
- `output_bindings`: named outputs or JSON paths produced by the trace.
- `postcondition`: generic verification contract, such as table row exists, text visible, download observed, or non-empty extraction.

This metadata should be optional and backward-compatible.

## Exported Script Strategy

The compiler should use dynamic bindings when available:

- Replace recorded values in embedded AI code only when they match declared input bindings.
- Keep stable UI anchors literal.
- Generate small generic helpers for table-row lookup and editable item-row filling when metadata indicates those patterns.

Helpers must be generic and operate on headers, labels, dynamic keys, and values. They must not mention eval app entities or fixed IDs.

## Test Strategy

Use focused unit tests for parser, extraction normalization, effect verification, trace metadata serialization, and compiler helper rendering. The tests must not depend on the eval app's fixed case IDs. They should use neutral examples such as invoices, projects, and purchase-like tables only where the behavior is generic.
