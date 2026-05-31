# ScienceClaw vs OpenClaw Browser Contract Comparison

## Purpose

This material is for architecture discussion, not direct implementation.

It answers four questions:

1. Where the current ScienceClaw browser snapshot direction is correct.
2. Where the current contract diverges from OpenClaw in a harmful way.
3. Whether ScienceClaw should directly reuse OpenClaw.
4. What browser-state contract should be adopted next if the project prefers
   better accuracy over tighter token budgets.

## Executive Summary

The current problem is not that ScienceClaw uses snapshots.

The real problem is that the current compact snapshot tries to serve too many
goals at once:

- planner context
- execution hints
- token compression
- diagnostic readability

That coupling is what makes list-selection tasks unstable.

OpenClaw takes a cleaner stance for browser execution:

- first produce a browser-side snapshot
- then operate through snapshot-backed refs
- accept that refs can become stale after page changes
- re-snapshot when needed

ScienceClaw should not directly replace its recording stack with OpenClaw, but
it should borrow this contract boundary.

Recommended direction:

```text
Keep ScienceClaw raw trace evidence.
Reduce aggressive compaction.
Add an execution-facing candidate/ref layer closer to OpenClaw.
```

## Current ScienceClaw Direction

ScienceClaw already has one important architectural choice that is directionally
correct:

```text
raw_snapshot = factual evidence
compact_snapshot = planner-facing representation
```

This is compatible with the project's trace-first recording principles:

- recording should preserve what the browser actually contained
- diagnostics should expose what was lost
- post-hoc compilation should use factual traces rather than runtime guesses

The issue is not the existence of `raw_snapshot`.
The issue is that `compact_snapshot` is still asked to do too much.

## What Happened In The Trending Failure

In the GitHub Trending case, the user instruction was:

```text
Click the second project.
```

The raw snapshot contained the right page facts:

- repo cards were present
- their visible order was present
- their titles and links were present
- the second visible repository was not `Anil-matcha / Open-Generative-AI`

But the compact layer exposed the page mainly as:

- `expanded_regions`
- `sampled_regions`
- `region_catalogue`
- many repository cards represented as `action_group`

This created two structural losses:

1. The visible candidate ordering was not preserved as a first-class contract.
2. The planner was still allowed to invent its own locator instead of consuming
   a stable candidate identity.

That is why the model could simultaneously believe:

- "the target is Anil-matcha"
- while generating `article.nth(1)`

The compact representation and the execution contract were no longer aligned.

## OpenClaw's Browser Contract

OpenClaw's browser documentation and public examples point to a different
contract shape:

```text
snapshot -> refs -> actions
```

Important traits of that model:

- The browser-side tool is responsible for producing an AI-usable page view.
- Actions are expected to target snapshot-derived refs.
- The system explicitly accepts that refs may become stale after DOM or page
  transitions.
- Re-snapshot is treated as normal protocol behavior, not as an exceptional
  repair hack.

This gives OpenClaw a cleaner division of responsibility:

- browser/client side decides what the action surface is
- model chooses among the surfaced options
- execution uses the surfaced identity instead of re-deriving DOM intent

This is the key part worth learning from.

## Side-By-Side Comparison

| Topic | ScienceClaw Current | OpenClaw Style | Assessment |
| --- | --- | --- | --- |
| Primary runtime artifact | `raw_snapshot` + `compact_snapshot` | browser snapshot with action refs | both are valid |
| Execution target | model-generated Playwright locator/code | snapshot-backed ref action | OpenClaw cleaner |
| Compression goal | strong token reduction, tiered summaries | action-surface clarity first | ScienceClaw currently over-compresses |
| Diagnostic value | strong, because raw evidence is retained | weaker as a trace/compile substrate | ScienceClaw stronger |
| Replay/compiler support | strong fit for trace-first architecture | not designed around post-hoc skill compilation | ScienceClaw should keep this |
| Candidate list handling | often flattened into `action_group` summaries | action identity exposed more directly | OpenClaw better for selection tasks |
| Failure recovery | planner + one repair over compact facts | re-snapshot and act on new refs | OpenClaw contract is more stable |

## What OpenClaw Gets Right

### 1. Client-Side Filtering Owns The Action Surface

The client/browser tool does not ask the model to rediscover the full DOM.
It first narrows the page into an operable action surface.

That is the main reason OpenClaw-like systems are more stable for navigation and
click tasks.

### 2. Identity And Action Stay Coupled

When an item is surfaced in the snapshot, the action entry is already tied to a
browser identity.

The model does not need to make a second independent guess such as:

```text
I think this is candidate B,
so I will now invent a new CSS or role locator for it.
```

### 3. Staleness Is Protocolized

OpenClaw-style refs are not assumed to be eternal.
Page changes invalidate refs, so the system re-snapshots.

That is a healthier model than pretending old locators remain semantically
correct across page transitions.

## What ScienceClaw Already Does Better

### 1. Raw Evidence Preservation

ScienceClaw preserves enough information for:

- debug dumps
- root-cause analysis
- comparison of raw vs compact loss
- post-hoc trace compilation

This is central to the project's architecture and should not be dropped.

### 2. Clear Trace-First Alignment

ScienceClaw is not only a runtime browser agent.
It is building a recording system whose outputs must later become replayable
skills.

That means the system needs richer evidence than a pure "click by ref" runtime
agent might require.

### 3. Compiler-Oriented Structure

The compiler needs:

- before/after page state
- recorded code or locator evidence
- structured output keys
- runtime result dependencies

OpenClaw's runtime browser contract does not directly solve that layer.

## Why Direct Reuse Is Not The Best Choice

Directly reusing OpenClaw as the browser layer would be attractive only if
ScienceClaw were trying to become a pure runtime browser operator.

That is not the project goal.

ScienceClaw still needs:

- trace-first recording evidence
- post-hoc skill compilation
- repair diagnostics
- output-key based cross-step dataflow

Direct reuse would likely force the project into one of two bad outcomes:

1. lose the richer trace evidence needed for compilation
2. wrap OpenClaw heavily until the integration cost exceeds the benefit

So the right conclusion is:

```text
Do not directly replace ScienceClaw with OpenClaw.
Do reuse the OpenClaw browser contract where it is clearly superior.
```

## Three Possible Paths

### Path A: Keep Current Compression Strategy And Tune Prompts

Idea:

- keep tiered compact snapshot as the default planner input
- add more rules and prompts for list-selection tasks

Advantages:

- lowest immediate code change
- preserves current token profile

Disadvantages:

- keeps the current structural loss
- pushes browser-state responsibility back to the model
- likely creates more repair and prompt debt

Assessment:

Not recommended.

### Path B: Adopt OpenClaw Whole-Style Runtime Contract

Idea:

- rework the recording-time browser runtime around snapshot-derived refs
- reduce planner freedom to invent DOM locators

Advantages:

- cleaner execution boundary
- better click/navigation stability

Disadvantages:

- does not naturally cover ScienceClaw's trace-first compiler needs
- large integration and adaptation cost
- risks weakening diagnostic richness

Assessment:

Useful as inspiration, not as a wholesale replacement.

### Path C: Dual-Layer Contract

Idea:

- keep `raw_snapshot` as factual evidence
- reduce aggressive compression
- add an execution-facing `candidate_list` or `action_snapshot`
- require planner to choose from surfaced candidates for selection tasks
- execute via surfaced refs or ref-like stable identities

Advantages:

- keeps trace-first evidence
- fixes the list-selection contract
- aligns execution identity with planner context
- avoids over-compression

Disadvantages:

- introduces another explicit snapshot layer
- requires planner contract tightening

Assessment:

Recommended.

## Recommended New Contract

The next browser-state contract should look like this:

```text
Layer 1: raw_snapshot
  factual evidence for diagnostics and compilation

Layer 2: planner_snapshot
  lightly structured, low-loss context for the recording planner

Layer 3: action_snapshot
  execution-facing candidates/refs for click and navigation steps
```

### Layer 1: raw_snapshot

Purpose:

- preserve factual browser evidence
- support debug dumps
- support raw vs compact loss analysis
- support future compiler logic

Rule:

- do not optimize this layer for token size

### Layer 2: planner_snapshot

Purpose:

- provide readable, low-loss context to the planner

Rule:

- stop aggressively summarizing candidate pages into small catalogues
- prefer structural pruning over semantic rewriting

For example:

- remove obvious noise
- keep visible titles, descriptions, hrefs, and ordering
- keep repeated candidate items as repeated items
- do not reorder by title when visible order matters

### Layer 3: action_snapshot

Purpose:

- provide stable execution targets

For selection tasks, each candidate should include at least:

- `order_index`
- `title`
- `summary` or `description`
- `href`
- `primary_action_ref`
- `bbox_y` or equivalent visible-order evidence

This layer should be closer to OpenClaw's ref contract.

## Compression Strategy After This Decision

Because the project is willing to spend more tokens for better accuracy, the
default strategy should change.

Previous implicit objective:

```text
compress as much as possible while keeping enough context
```

Recommended objective:

```text
preserve as much task-critical structure as possible,
then remove only obvious noise
```

This means:

- no more aggressive top-K expansion as the default worldview
- no more relying on catalogue summaries for candidate selection
- no more title-based reordering of page regions when visible order matters

The right unit of optimization is no longer "smallest snapshot".
It is "lowest information loss under an acceptable token budget".

## Practical Rules To Adopt

### Rule 1: Candidate Pages Must Stay Ordered

Examples:

- search results
- repository cards
- product lists
- PR or issue lists
- article feeds

These should be represented as an ordered candidate structure, not mainly as
isolated `action_group` summaries.

### Rule 2: Planner Must Not Re-Derive Candidate Identity

If the browser-side layer already surfaced:

- candidate 1
- candidate 2
- candidate 3

then the planner must choose from those candidates instead of inventing an
independent DOM locator.

### Rule 3: Execution Should Prefer Ref-Backed Actions

For click/navigation tasks, use browser-surfaced action identity first.
Only fall back to free-form generated locators when no surfaced identity exists.

### Rule 4: Re-Snapshot After State Changes Is Normal

Do not treat stale refs or invalidated candidates as exceptional logic.
Treat them as a signal that the action surface changed and the page should be
re-observed.

## What Should Not Change

The following project commitments should stay:

- trace-first recording
- bounded repair
- raw failure facts over experience hints
- post-hoc compiler ownership of generalization
- avoidance of site-specific runtime architecture

This proposal changes the browser-state contract, not the project's core
architecture.

## Final Recommendation

ScienceClaw should not directly reuse OpenClaw as its browser system.

ScienceClaw should reuse the part OpenClaw gets most right:

```text
browser-side action surface first,
model choice second,
execution by surfaced identity third
```

The best next step is not "copy OpenClaw".
The best next step is:

```text
keep ScienceClaw trace evidence,
weaken aggressive compression,
add OpenClaw-style candidate/ref execution contracts
```

That path preserves the strengths of both systems without forcing ScienceClaw to
abandon its trace-first compiler architecture.

## Suggested Follow-Up Questions

If this direction is accepted, the next design discussion should answer:

1. Should `planner_snapshot` and `action_snapshot` be two separate payloads or
   one payload with two sections?
2. Should list-selection tasks bypass free-form code generation and use a more
   constrained planner output schema?
3. Which page classes should get ordered candidate treatment first:
   repository cards, search results, or generic repeated cards?

## References

- OpenClaw browser tool documentation: <https://docs.openclaw.ai/tools/browser>
- OpenClaw FAQ: <https://docs.openclaw.ai/help/faq>
- ScienceClaw trace-first architecture:
  [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- ScienceClaw failure repair policy:
  see AGENTS.md RPA/Agent architecture rules 2-5 and current repair evidence in
  [EV-001 RPA Trace Source Convergence](../evidence/EV-001-rpa-trace-source-convergence.md)
- ScienceClaw snapshot candidate analysis:
  [snapshot-candidate-collection-analysis.md](snapshot-candidate-collection-analysis.md)
