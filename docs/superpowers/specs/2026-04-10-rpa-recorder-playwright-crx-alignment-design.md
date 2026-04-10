# RPA Recorder Playwright-CRX Alignment Design

## Summary

The current RPA recorder still diverges from Playwright recorder semantics in three places that matter most for correctness:

- the injected browser script delays and simplifies event capture, which causes missed actions and unstable ordering
- the custom locator generator approximates Playwright selector generation, but it does not perform strict uniqueness validation and cannot reliably disambiguate repeated elements
- the Python code generator cannot fully preserve the semantics of recorded actions such as `press("Enter")` causing navigation

This design keeps the existing FastAPI, Python Playwright session management, and Vue pages, but replaces the current recorder-v2 internals with a recorder pipeline intentionally aligned with `playwright-crx` and Playwright recorder behavior.

The goal is not to import the CRX product UX. The goal is to make recording truth, locator selection, and generated playback code behave like Playwright recorder semantics while remaining compatible with the current product architecture.

## Design Goals

- Record fast user interactions without losing actions or reversing their order
- Use locator selection semantics close to Playwright recorder instead of heuristic shortcuts
- Preserve replay semantics for navigation, popup, download, and repeated-element targeting
- Keep the current backend API surface and frontend pages working with targeted payload upgrades
- Add regression tests that lock down the recorder behavior before the implementation changes ship

## Non-Goals

- Replacing the entire Python recorder with a separate Node service in this change
- Embedding the CRX side panel, extension UX, or Playwright Inspector UI
- Preserving every historical quirk of previously recorded steps when those quirks contradict correct playback semantics
- Redesigning the recorder frontend beyond the data needed to present improved locator candidates and validation

## Current Problems

### Event Capture Problems

The injected recorder script in [manager.py](D:/code/MyScienceClaw/.worktrees/feature-recorder/RpaClaw/backend/rpa/manager.py) records only a narrow subset of browser events and uses a `1500ms` debounce for `input`. This creates three classes of bugs:

- typed text can be lost entirely when the page navigates before the debounce flushes
- `press("Enter")` is recorded before the preceding `fill`, so recorded step order becomes incorrect
- rapid interactions are processed according to backend arrival timing instead of a stable recorder-side sequence

By contrast, `playwright-crx` records `fill` immediately on `input`, maintains active/hovered models, and separates input, key, and pointer semantics into explicit recorder tools.

### Locator Problems

The current locator generator prefers a hand-written score order and then uses relaxed uniqueness checks. Several candidate types are treated as effectively unique even when they are not. When no candidate is unique, the code falls back to a CSS path and marks the selected candidate as if it had a strict single match.

This causes the configure page to show a plausible default candidate while replay may still resolve multiple elements or the wrong element.

`playwright-crx` instead generates multiple selector token combinations, evaluates them against the actual DOM, and attaches `nth` only when needed to make the target strict.

### Code Generation Problems

The generator currently upgrades only `click` into navigation-aware actions. A recorded `press("Enter")` that submits a form is emitted as a plain `locator.press("Enter")` followed by a later navigation step, which changes the real semantics of the interaction. This is especially problematic for forms whose submit action depends on front-end event handlers, validation state, or synchronous side effects.

## Alternatives Considered

### 1. Patch The Existing Recorder Minimally

This would keep the current event model and locator structure, only fixing the obvious debounce and uniqueness bugs.

Pros:

- least code movement
- lowest short-term risk

Cons:

- preserves the current recorder architecture that already drifted away from Playwright semantics
- leaves repeated-element targeting, active-target stability, and generated navigation semantics only partially fixed

### 2. Align The Existing Python Recorder With `playwright-crx` Semantics

This keeps the current Python-owned runtime and API surface, but refactors the injected recorder script, locator candidate generation, step model, and generator logic to behave like Playwright recorder semantics.

Pros:

- fixes the root correctness issues without introducing a new runtime service
- preserves the current backend routes, persistence model, and frontend structure
- can be covered by the repository's existing Python backend tests

Cons:

- requires deeper changes across event capture, step models, generator output, and configure UI
- still leaves selector generation implemented locally rather than imported directly from Playwright internals

### 3. Replace The Recorder With A New Node Runtime Immediately

This would move recorder truth to a dedicated Node engine and make Python only an orchestration layer.

Pros:

- best long-term alignment with Playwright internals

Cons:

- significantly larger scope than the requested fix
- forces protocol, process, and architecture changes not required to solve the current bugs

### Chosen Approach

Option 2 is the chosen design. It fixes the current correctness failures now, keeps scope bounded to the recorder pipeline, and leaves room for a future engine split if needed.

## Architecture

### Recorder Pipeline

The recorder pipeline remains:

1. browser-side injected script captures trusted user interactions
2. events are bridged into Python through `context.expose_binding`
3. the session manager normalizes and persists ordered steps
4. the generator converts those steps into Playwright code

What changes is the quality of the data at each boundary.

### Browser-Side Action Model

The injected script should move from stateless per-event locator recomputation to a lightweight recorder state model:

- `hovered target`: current element under pointer after retargeting
- `active target`: element that received focus or the interaction anchor for the current action
- `sequence`: monotonically increasing integer assigned before emitting every action

The script must:

- record `fill` immediately on `input`
- record `press` independently on `keydown` when the key should become a Playwright `press`
- keep `click`, `dblclick`, `auxclick`, and select/input-specific actions distinct
- stop using the current one-second same-locator click dedupe as a blanket rule

The browser-side payload becomes authoritative for ordering. Python should not infer ordering from asynchronous callback arrival alone.

### Step Payload Shape

The existing `RPAStep` model will be extended rather than replaced. New or upgraded fields should include:

- `sequence`: integer, recorder-side order key
- `action`: explicit action kind such as `click`, `dblclick`, `fill`, `press`, `select`
- `target`: canonical locator payload selected by strict validation
- `locator_candidates`: ordered candidate list including strict match count and selected marker
- `signals`: runtime signals such as navigation, popup, download
- `element_snapshot`: debug metadata used only for diagnostics and fallback UI display

The API should remain backward compatible for current consumers by keeping current top-level names where possible.

## Locator Selection Design

### Candidate Generation

Candidate generation should follow the same philosophy as Playwright recorder:

- retarget to the closest interactive ancestor when appropriate
- generate text and non-text candidates separately
- evaluate exact candidates before broader fallback candidates
- include parent-chain combinations when the target itself is not unique
- produce `nth` only when strict uniqueness cannot be achieved otherwise

The current static score list can remain as a rough ordering aid, but only if every chosen candidate is validated by actual DOM resolution against the target element.

### Strictness Rules

The selected candidate must never be labeled strict unless the candidate actually resolves exactly one matching target in the current scope.

Rules:

- `strict_match_count == 1` only when actual evaluation yields exactly one match
- fallback candidates must preserve their real match count
- `nth` is allowed when necessary to make the chosen candidate strict
- the configure page should surface non-strict candidates honestly instead of showing them as safe defaults

### Candidate Representation

Locator payloads should be expressive enough to generate faithful Python Playwright code. The model should support:

- `role`
- `testid`
- `label`
- `placeholder`
- `alt`
- `title`
- `text`
- `css`
- `nested`
- `nth`

`nth` should be a first-class recorded concept rather than an implicit UI-only suggestion.

## Event Ordering Design

Recorder-side ordering must be stable even when emission crosses asynchronous Python bindings.

Design rules:

- every emitted action gets a `sequence` before the binding call
- Python stores steps ordered by `sequence`
- where the current session already contains steps with higher arrival order but lower sequence correctness, insertion or local reordering is allowed within the current recording buffer
- `timestamp` remains useful for diagnostics, but `sequence` is the ordering authority

This directly fixes the current `fill` then immediate `Enter` case.

## Runtime Signal Design

Signals should be captured close to the original action so the generator does not need to guess later.

The session manager should support:

- navigation following `click` or `press`
- popup creation following `click`
- download following `click`

This means navigation-aware upgrades should apply to both click-like and press-like actions when the recorded signal indicates that the action itself caused the page transition.

## Code Generation Design

The generator should continue emitting Python Playwright async code, but it must preserve the semantics of the recorded action:

- `click` causing navigation becomes a navigation-wrapped click
- `press` causing navigation becomes a navigation-wrapped press
- popup and download remain attached to the triggering action, not reconstructed as separate unrelated operations
- `nth` locator payloads generate `.nth(index)` or `.first`/`.last` directly

The generator should not silently convert semantically different actions into the same output just because they share a target element.

## Frontend Impact

The recorder and configure pages do not need structural redesign. They need better data fidelity:

- candidate chips must reflect real strictness
- selected locator summaries must display `nth` and nested locators correctly
- validation status should distinguish strict success from fallback or ambiguous selection

No route changes are required.

## Testing Strategy

This change must be implemented test-first.

### Backend Tests

The main regression coverage belongs in:

- `RpaClaw/backend/tests/test_rpa_manager.py`
- `RpaClaw/backend/tests/test_rpa_generator.py`

Required failing tests before implementation:

- input followed immediately by Enter records `fill` before `press`
- emitted events arriving out of order are stored according to `sequence`
- ambiguous repeated elements produce a strict chosen locator only when `nth` or a stricter parent chain disambiguates them
- `press` with navigation signal generates navigation-wrapped code rather than a detached `goto`

### UI/Contract Sanity

The configure page and recorder page need at least a targeted sanity pass to ensure the new candidate payloads still render correctly. If existing frontend tests are absent, this remains a manual verification item for the implementation plan.

## Risks

- The injected recorder script will become more stateful, so careless changes could create cross-event leakage if state is not reset consistently.
- Locator payload upgrades may require synchronized updates in both Python generator logic and Vue rendering helpers.
- Historical sessions recorded with old payloads must still be replayable. The generator therefore needs tolerant parsing for older locator shapes where feasible.

## Rollout Notes

The change should be delivered as one recorder-alignment slice rather than a long-lived partial migration. Mixed semantics between old and new recorder behavior inside the same branch would make the regression surface harder to reason about.

The implementation should therefore proceed in this order:

1. lock down failures with tests
2. refactor event capture and step ordering
3. refactor locator generation and selection
4. upgrade code generation
5. verify frontend rendering and export flows

## Success Criteria

- fast input plus immediate Enter no longer loses text or reverses order
- repeated elements default to a strict, replayable locator or are shown as ambiguous
- generated code preserves the action that caused navigation instead of replaying a different sequence
- targeted backend tests pass and cover the fixed regressions
