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

## Recording Command Boundary

The recording runtime should not infer business intent by deleting natural-language wrapper sentences or negative constraints from the user's message. That approach is brittle because evaluation harness prompts and real business guardrails can use the same words, such as "do not" or "不要".

The implemented boundary is structural:

- `POST /api/v1/rpa/session/{session_id}/chat` accepts an optional `business_instruction`.
- Interactive users can keep sending only `message`; behavior stays backward-compatible.
- Evaluation and automation callers can send a rich `message` for UI/log context plus a separate `business_instruction` for the trace-first runtime.
- `RecordingRuntimeAgent.run()` receives the actual business goal and no longer contains `context_markers` or template-specific prompt filtering.

This keeps eval harness setup instructions out of the runtime planner without hard-coding the eval prompt template into RpaClaw.

## Snapshot Extraction

`extract_snapshot` should support both canonical field lists and planner-friendly maps:

- Canonical: `fields: [{"label": "合同编号", "value": "CT-..."}]`
- Compatible: `fields: {"合同编号": "CT-..."}`

Execution should convert both into a normalized field list and keep signal metadata usable by the compiler.

Snapshot collection uses semantic DOM structure as the default path:

- Tables: native `table`, ARIA grid/table roles, headers, row-local cells, row-local actions, and editable controls.
- Details: `section`, `article`, `form`, `fieldset`, ARIA regions/groups, `data-*`, `dl/dt/dd`, and two-column key/value tables.
- Modals: `[role="dialog"]` and `[aria-modal="true"]` are the default semantic roots.

Framework-specific selectors are isolated behind adapter registries:

- `tableViewAdapters` currently contains a Jalor iGrid adapter that outputs the same `table_view` schema as the semantic collector.
- `modalViewAdapters` contains Element, Ant, Vant, and generic class-modal adapters that output the same `modal_dialog` schema as the semantic collector.

Framework adapters should remain optional collection adapters, not business logic and not default locator rules embedded in generated skills.

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

Current implementation wires this metadata through the real recording path:

- The planner schema documents `input_bindings`, `output_bindings`, and `postcondition`.
- `_accepted_trace()` copies these fields from the accepted plan into `RPAAcceptedTrace`.
- `RPAAcceptedTrace` serializes the metadata with default empty dictionaries.
- The compiler consumes declared `input_bindings` to parameterize embedded AI code, and consumes compilable postconditions to allow bounded recovered attempts.

The compiler must only rewrite values explicitly declared in `input_bindings`. It must keep UI labels, placeholders, roles, titles, table headers, and other stable anchors literal.

## Exported Script Strategy

The compiler should use dynamic bindings when available:

- Replace recorded values in embedded AI code only when they match declared input bindings.
- Keep stable UI anchors literal.
- Generate small generic helpers for table-row lookup and editable item-row filling when metadata indicates those patterns.

Helpers must be generic and operate on headers, labels, dynamic keys, and values. They must not mention eval app entities or fixed IDs.

For snapshot extraction scripts, the compiler now prefers replayable structural evidence in this order:

1. Explicit value locator.
2. Field locator or stable `data-prop`.
3. URL path extraction.
4. Text pattern extraction.
5. Observed DOM label adjacency.

Recorded unique text is treated as evidence only, not as a primary replay locator, because runtime data can change. If required fields do not have replayable evidence, the compiler falls back to runtime semantic instruction instead of generating a deterministic script that would silently use recorded data.

The label-adjacency extractor is generic: it uses ARIA label relationships, `label[for]`, `dt/dd`, table cells, sibling nodes, parent text, ancestor siblings, inputs, outputs, and `data-value`. It does not include AUI, Element, Ant, Jalor, eval app, GitHub, or fixed case selectors.

## Evaluation Framework

The evaluation runner supports `--verify-replay`, which validates the full recording lifecycle:

- Record through RpaClaw.
- Generate the skill script.
- Reject scripts that still call runtime AI unless explicitly allowed.
- Execute the generated script.
- Apply expected API, telemetry, output, and download assertions.

The runner now passes `business_instruction` separately from its wrapper prompt so RpaClaw can evaluate real recording behavior without prompt-template coupling.

Latest verified full run after the implementation:

- Date: 2026-04-29
- Command: `uv run python rpa-eval-app/evals/runner.py --all --verify-replay --case-timeout-s 240 --replay-timeout-s 180 --rpaclaw-url http://127.0.0.1:12011 --eval-backend-url http://127.0.0.1:8085 --eval-frontend-url http://127.0.0.1:5175 --model gpt-5.4-mini`
- Result: 7 passed, 5 failed, 58.3% pass rate.

Passing cases in that run:

- `approval_high_priority_001`
- `contract_extract_001`
- `login_navigation_001`
- `purchase_order_generate_001`
- `purchase_request_create_001`
- `report_async_download_001`
- `report_contract_export_001`

Known remaining failure classes:

- Recording timeouts on complex navigation/edit flows.
- Replay starting state mismatch for multi-page data-transfer flows.
- Some record-stage failures after bounded repair attempts.

## Test Strategy

Use focused unit tests for parser, extraction normalization, effect verification, trace metadata serialization, and compiler helper rendering. The tests must not depend on the eval app's fixed case IDs. They should use neutral examples such as invoices, projects, and purchase-like tables only where the behavior is generic.
