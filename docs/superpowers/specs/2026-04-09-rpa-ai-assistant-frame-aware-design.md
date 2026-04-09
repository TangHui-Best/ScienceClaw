# RPA AI Assistant Frame-Aware Execution Design

## Summary

The current RPA AI recording assistant can execute simple actions on the active Playwright `Page`, but it still uses a main-document-only mental model:

- page observation only extracts interactive elements from the main document
- the LLM is expected to infer iframe context and generate raw `page.locator(...)` code on its own
- successful AI actions are usually stored as opaque `ai_script` steps instead of Recorder V2 enriched steps

This breaks on iframe-heavy pages. Manual recording works because Recorder V2 already captures `frame_path`, locator candidates, and replay metadata, but AI-assisted actions do not share that runtime model.

This design upgrades the AI assistant to use the same frame-aware, tab-aware, replay-aligned semantics as Recorder V2. The assistant should automatically search across frames, prefer structure-based self-adapting locators, and persist successful atomic actions as enriched recorder steps.

## Goals

- Let the AI assistant automatically find and act on targets inside nested iframes
- Keep AI observation, execution, and persistence aligned with Recorder V2 frame semantics
- Support self-adapting position-based instructions such as "click the first result" and "get the first item"
- Prefer collection-aware and structure-aware locators over hard-coded content
- Preserve popup, navigation, and active-tab behavior already introduced in the multi-tab recorder model
- Expose enough diagnostics for operators to understand which frame and locator were chosen

## Non-Goals

- Replacing Recorder V2 with a separate assistant-only runtime
- Solving arbitrary multi-step business logic purely through structure-aware actions
- Guaranteeing perfect identification for every ambiguous iframe page without fallback or clarification
- Removing `ai_script` support entirely for advanced custom logic

## Current Problem

The assistant currently diverges from Recorder V2 in three places:

1. observation:
   - `backend/rpa/assistant.py` extracts elements through one `page.evaluate(...)`
   - iframe documents are invisible to the assistant prompt unless the model guesses them
2. execution:
   - generated code only receives `page`
   - the model is implicitly asked to discover frame chains and write `frame_locator(...)` logic itself
3. persistence:
   - successful actions are usually saved as `ai_script`
   - `frame_path`, `locator_candidates`, and validation data are not preserved like manual Recorder V2 steps

The result is an inconsistent product model:

- manual recording is frame-aware
- AI execution is frame-blind
- replay quality differs depending on whether the user clicked or described the same action

## Design Principles

- Recorder and assistant must share one runtime truth
- frame context must be explicit, never reconstructed later from a bare locator string
- structure and semantics are more stable than dynamic content
- "first" and "nth" must be interpreted inside a detected collection, not across the entire page
- AI should describe intent; the backend should own deterministic frame resolution and execution
- successful AI actions should persist as the same enriched step model used by Recorder V2 whenever possible

## Proposed Architecture

### Chosen Direction

The AI assistant becomes frame-aware in three linked phases:

1. `observe`
   - build a tab-scoped, frame-aware page snapshot
2. `act`
   - resolve targets across frames with backend-owned helper logic
3. `persist`
   - compile successful atomic actions into Recorder V2 enriched steps

This keeps the assistant inside the existing Python backend and Playwright runtime, and it reuses Recorder V2 concepts instead of inventing a parallel action model.

### Rejected Direction

Do not treat iframe support as a prompt-only problem by merely telling the model to write `page.frame_locator(...)`.

That approach is insufficient because:

- the model still cannot see a trustworthy frame inventory
- it forces frame-chain guessing into prompt behavior
- it does not improve persistence or replay correctness
- it fails to solve self-adapting position-based actions reliably

## Runtime Model

### Assistant Observation Snapshot

Replace the current flat main-document element dump with a frame-aware snapshot structure:

```json
{
  "tab_id": "tab-1",
  "url": "https://example.com",
  "title": "Example",
  "frames": [
    {
      "frame_id": "main",
      "frame_path": [],
      "frame_hint": "main document",
      "url": "https://example.com",
      "elements": [],
      "collections": []
    },
    {
      "frame_id": "frame-2",
      "frame_path": ["iframe[title='editor']"],
      "frame_hint": "iframe title=editor src*=editor",
      "url": "https://cdn.example.com/editor",
      "elements": [],
      "collections": []
    }
  ]
}
```

Each frame section should include:

- `frame_path`
- frame summary fields such as title/name/src-derived hint
- a bounded list of interactive elements
- a bounded list of detected repeated collections
- per-element locator candidate summaries

This snapshot becomes the main assistant observation contract.

### Frame Traversal

The observation builder should traverse:

- `page.main_frame`
- all descendant `child_frames`

It should reuse Recorder V2 frame-path logic where possible so the assistant and recorder do not diverge on how a frame chain is represented.

If detailed DOM extraction is limited in some cross-origin cases, the system should still preserve:

- frame identity
- frame path
- coarse frame hints

Execution must not depend on the snapshot containing full DOM details for every frame.

## Observe Phase

### Element Extraction

For each frame, extract visible interactive targets using the same broad categories already used by the recorder:

- `a`
- `button`
- `input`
- `textarea`
- `select`
- semantic roles such as button, link, menuitem, checkbox, radio, tab
- contenteditable targets

Each element entry should include:

- tag and role
- accessible name or label summary
- placeholder or title when useful
- condensed element text when stable
- primary locator candidate
- candidate diagnostics summary
- `frame_path`

The assistant prompt should no longer present one flattened "page element list". It should present a frame-grouped view so the model can see which targets live in which iframe.

### Collection Detection

To support self-adapting instructions such as "click the first result", the observation layer must detect repeated collections inside each frame.

Examples:

- search result lists
- table rows
- card grids
- menus
- repeated form option groups

Each collection summary should contain:

- a `collection_hint`
- container description
- item description
- item count
- the frame that owns the collection

Example:

```json
{
  "kind": "search_results",
  "frame_path": ["iframe[title='preview']"],
  "container_hint": {"role": "list"},
  "item_hint": {"role": "link"},
  "item_count": 10
}
```

This lets the assistant reason about "first result" as a position inside a collection rather than falling back to a hard-coded title.

## Act Phase

### Action Model

The assistant should prefer structured action intents over free-form Playwright code for atomic browser interactions.

Suggested intent shape:

```json
{
  "action": "click",
  "target_hint": {
    "role": "button",
    "name": "Send"
  },
  "ordinal": "first"
}
```

For collection-based actions:

```json
{
  "action": "extract_text",
  "collection": {
    "container_hint": {"role": "list"},
    "item_hint": {"role": "link"}
  },
  "ordinal": "first"
}
```

The backend then converts that intent into deterministic frame-aware execution.

### Backend-Owned Helpers

Introduce assistant execution helpers that search and act across the active tab snapshot:

- `click_best(...)`
- `fill_best(...)`
- `press_best(...)`
- `extract_best(...)`
- `resolve_collection_item(...)`

These helpers should:

1. collect candidates across frames
2. score and rank candidates using Recorder V2 locator semantics
3. resolve the execution scope:
   - main document: `page.locator(...)`
   - iframe: chained `frame_locator(...)`
4. execute the action
5. capture runtime signals such as popup and navigation
6. return the resolved target metadata for persistence

The model is no longer responsible for guessing frame chains during common actions.

### Candidate Ranking

Candidate ranking should use the same broad preference model as Recorder V2:

1. locator quality
   - `testid`
   - `role + name`
   - `placeholder`
   - `label`
   - `alt`
   - `text`
   - `title`
   - css fallback kinds
2. uniqueness
   - strict unique beats ambiguous
3. actionability
   - visible and interactable targets win
4. frame preference
   - recently interacted frame can outrank unrelated frames when scores are close

This preserves consistency with recorder-generated locator candidates.

## Position-Based Semantics

### Meaning Of `first` And `nth`

For assistant instructions like "click the first element" or "get the first result", position semantics must be:

- within the chosen collection
- within the chosen frame
- restricted to visible actionable matches
- ordered by DOM order

The assistant must not interpret `first` as:

- the first matching element across the whole page
- the first match across all frames merged together
- a concrete item identified by dynamic text observed in one session

This is critical for self-adapting behavior when page content changes.

### Stability Rules

The assistant should prefer:

- collection + item semantics
- role-based locators
- structural selectors that survive data churn

The assistant should avoid when the user asked for a position-based action:

- hard-coding article titles
- hard-coding search result text
- hard-coding data-driven href values

Example:

- good: "first result card link in the search results collection"
- bad: "click the link with yesterday's top article title"

## Persistence Model

### Preferred Persistence

When a structured atomic action succeeds, persist it as a Recorder V2 style enriched step, not only as an opaque `ai_script`.

Preferred stored actions:

- `click`
- `fill`
- `press`
- `select`
- `navigate_click`
- `open_tab_click`

Important persisted fields:

- `target`
- `frame_path`
- `locator_candidates`
- `validation`
- `signals`
- `tab_id`
- `source_tab_id`
- `target_tab_id`
- `description`

This lets generator and configure flows treat AI and manual steps uniformly.

### Collection Metadata

For collection-driven actions, enrich persisted AI-originated steps with additional metadata even if the generator does not consume all of it immediately:

- `collection_hint`
- `item_hint`
- `ordinal`
- `resolved_target`

This preserves enough structure for future replay improvements and configure diagnostics.

### Fallback Persistence

Keep `ai_script` for cases where the user genuinely needs custom logic:

- loops
- conditionals
- bulk extraction
- multi-statement transformations

Even in this fallback mode, attach as much resolved metadata as possible:

- `frame_path`
- `tab_id`
- `resolved_targets`
- `signals`

That keeps iframe execution observable instead of black-box.

## Failure Recovery

### Failure Categories

The assistant should classify common frame-related failures:

- `not_found_in_main_frame`
- `found_in_multiple_frames`
- `locator_ambiguous`
- `element_not_actionable`
- `frame_detached`
- `cross_origin_snapshot_limited`

### Automatic Recovery Rules

Default behavior should stay automatic:

- if the main frame has no hit but one iframe has a strict-unique candidate, execute there directly
- if multiple frames match and one candidate clearly outranks the others, choose it automatically
- if the selected frame reloads or detaches, rebuild resolution once and retry
- if observation is limited but Playwright frame execution is still possible, attempt execution rather than failing early

Automatic retry should stay bounded. Do not silently brute-force every weak candidate forever.

### Ambiguity Escalation

When several frames remain plausible with similar scores, return diagnostics to the model and UI rather than pretending certainty.

Useful diagnostics:

- candidate frame summaries
- why the first candidate failed
- which locator kinds were tried
- whether ambiguity came from repeated collections

This allows a later assistant turn to ask for a narrower intent if needed.

## Prompt Model

### Assistant Responsibilities

The assistant model should focus on:

- understanding user intent
- choosing action type
- selecting collection or target semantics
- refining strategy after diagnostics

The backend should own:

- frame traversal
- candidate generation
- deterministic ranking
- runtime execution
- signal capture
- enriched step persistence

### Prompt Rules

Prompt guidance should explicitly teach:

- prefer structure-aware intent over hard-coded page content
- use collection semantics for `first`, `nth`, and list/table/card actions
- avoid dynamic text or href hard-coding unless the user explicitly asked for a specific content value
- rely on assistant helper capabilities for frame-aware execution

Do not keep the current prompt assumption that the model should solve iframe targeting by hand-written raw Playwright code in routine cases.

## Frontend Diagnostics

The recorder AI panel should expose enough execution metadata to make iframe behavior understandable.

Useful UI fields:

- resolved frame summary
- selected locator kind
- whether auto cross-frame retry happened
- runtime success or failure reason
- collection summary when the action used `first` or `nth`

The configure page should also display frame-aware AI-originated steps the same way it displays manual frame-aware steps.

## Backend Changes

### `backend/rpa/assistant.py`

Refactor the assistant around the new flow:

- replace the flat page element extraction with frame-aware snapshot building
- add structured intent execution helpers
- preserve a fallback path for explicit custom code
- save successful atomic actions as enriched steps when possible
- include collection-aware semantics for `first` and `nth`

### `backend/rpa/manager.py`

Reuse or expose Recorder V2 utilities needed by the assistant:

- frame-path construction
- locator candidate generation or selection helpers
- validation summary generation
- tab-aware runtime signal capture

The assistant should consume recorder semantics, not duplicate a subtly different implementation.

### `backend/route/rpa.py`

The assistant endpoint contract may need to return richer execution events:

- frame resolution summary
- locator summary
- retry diagnostics
- structured persisted step payload

### `frontend/src/pages/rpa/RecorderPage.vue`

Update the AI panel to show:

- resolved frame information
- collection/ordinal execution summary
- structured step details after success
- actionable failure diagnostics after bounded retries

## Testing Strategy

### Assistant Observation Tests

Add tests proving:

- iframe elements appear in assistant observation
- nested frame paths are preserved
- collection summaries are grouped per frame
- snapshot output remains bounded for token safety

### Assistant Execution Tests

Add tests proving:

- click inside a nested iframe resolves and executes successfully
- extraction inside iframe returns data successfully
- `first` resolves to the first visible actionable item within a detected collection
- position-based actions do not hard-code specific observed content
- execution prefers a better iframe candidate over a weaker main-frame guess

### Persistence Tests

Add tests proving:

- successful atomic assistant actions persist `frame_path`
- persisted assistant steps include locator diagnostics
- popup and same-tab navigation still upgrade to `open_tab_click` and `navigate_click`
- collection-driven actions preserve ordinal metadata

### UI Tests

Add tests proving:

- recorder AI panel surfaces resolved frame summary
- configure page shows frame-aware AI-originated step metadata
- ambiguous cross-frame failures expose diagnostics instead of a generic timeout only

## Rollout Plan

1. Introduce frame-aware observation snapshots.
2. Introduce backend-owned frame-aware action helpers.
3. Persist successful atomic AI actions as enriched steps.
4. Update prompts to prefer structured intent and collection semantics.
5. Add recorder UI diagnostics for frame and collection resolution.

This order delivers the correctness gains first and treats prompt/UI updates as downstream improvements rather than the primary fix.

## Conclusion

The AI recording assistant should not solve iframe interaction by prompt tricks alone. It needs the same frame-aware runtime model already adopted by Recorder V2.

The correct optimization is to make AI observation frame-aware, move cross-frame target resolution into deterministic backend helpers, treat collection-based `first` and `nth` actions as structure-aware semantics, and persist successful atomic actions as enriched Recorder V2 steps. That gives iframe support, self-adapting list actions, and replay alignment under one coherent design.
