# RPA Failure Repair Policy

## Purpose

Recording-time natural-language commands can fail because LLM-generated Playwright code may choose the wrong selector, wait for the wrong condition, navigate to an unexpected page, or return empty data. The repair policy defines how the system should respond without turning experience into a brittle rule engine.

## Core Principle

```text
Raw failure facts are authoritative.
Experience hints are advisory only.
```

A repair prompt must prioritize:

- User instruction.
- Current page facts.
- Failed plan/code.
- Raw error log.
- Execution result.
- Page state and snapshot after failure.

Failure hints may suggest a direction, but must not override the facts.

## Repair Bound

Recording-time repair is intentionally limited:

```text
first attempt -> if failed, one repair attempt -> accept trace or fail gracefully
```

More repair loops make recording slower, increase token cost, and can amplify instability. If one repair is not enough for a class of failures, improve the runtime evidence, prompt, compiler, or user workflow rather than adding open-ended retries.

## Failure Types

Current lightweight failure types:

- `selector_timeout`: a selector or locator did not appear in time.
- `strict_locator_violation`: a locator matched multiple candidates.
- `element_not_visible_or_not_editable`: Playwright found or attempted an element, but it was not actionable.
- `empty_extract_output`: execution completed but returned no meaningful data.
- `navigation_timeout_or_network`: navigation or network loading failed.
- `syntax_or_runtime_code_error`: generated Python failed before completing the browser task.
- `wrong_page_or_no_goal_progress`: execution did not create the expected visible effect.
- `unknown`: no known pattern matched.

There is intentionally no confidence score. The goal is not to build another classifier system; the goal is to give the next repair attempt a small amount of context.

## Planner Contract Debugging

Trace-first planner failures must be debugged at the LLM call boundary before changing prompts, parsers, or repair rules. Do not collapse distinct problems into a generic "model error".

First collect these facts:

- Current user id and RPA session owner id.
- Selected `model_config.id`, owner `user_id`, and `is_system`.
- Effective `model_name`, `base_url`, `max_tokens`, streaming mode, retry/timeout settings, and relevant `model_kwargs`.
- `message_count`, `total_message_chars`, and response preview.
- Whether the target value exists in raw snapshot, compact snapshot, or neither.
- Planner raw output shape: pure JSON, JSON fenced by prose, direct Python code, truncated JSON, or semantically valid JSON with bad code.

"Same model service" is not sufficient evidence that two calls are equivalent. The same GLM endpoint can behave differently when the path changes from DS env fallback to UI model config, when `max_tokens` differs, when the call is streaming vs non-streaming, or when the compact snapshot grows.

Default diagnostics should stay lightweight:

- Keep configured/effective model summaries, prompt sizes, and response preview.
- Do not store full prompt or snapshot previews by default.
- Use `RPA_LLM_DIAGNOSTIC_PROMPT_PREVIEW=true` only during focused local debugging.

Structured-output planner calls should declare their own output-token budget. They should not blindly inherit a low global chat-oriented `MAX_TOKENS` value, because a truncated plan is not repairable JSON.

## Actionability Failures

Playwright actionability failures are different from missing selectors.

Example:

```text
locator("#kw") resolved to an input
but element is not visible
```

This means the locator matched something, but it was not visible, enabled, or editable. Repair should not only try a different selector. It should inspect the page after failure and choose a truly actionable candidate.

For explicit form-filling commands, repair should prefer visible, enabled, editable inputs. For goal-oriented search commands, direct navigation to an encoded search-results URL may be more stable than simulating typing.

## Search Tasks

Search tasks have two different meanings:

- Goal-oriented: "search X on Baidu" means reaching search results for X.
- UI-specific: "fill X into the search box and click search" means exercising the page's input and button.

The first can use a search-results URL when appropriate. The second should interact with a visible, enabled, editable search input.

This is a general search-engine policy, not a Baidu-specific rule.

## What Not To Do

- Do not block non-dangerous code before execution just because it looks brittle.
- Do not add site-specific rules as the main repair strategy.
- Do not let failure hints become planner instructions with higher priority than raw logs.
- Do not hide raw errors from the user.
- Do not add unlimited repair loops.

## Safety Boundary

Safety issues are different from stability issues.

Pre-execution blocking is appropriate for:

- Shell execution.
- Destructive filesystem operations.
- Infinite loops.
- Local sensitive path access.
- Network requests outside the browser context when not explicitly required.

Stability issues such as selector brittleness, empty extraction, or slow navigation should be handled through execution evidence and repair, not pre-execution blocking.
