---
doc_kind: lesson
id: LL-001
title: Harness Feature Evidence Closeout Miss
status: active
feature_ids: [F002]
created: 2026-05-18
updated: 2026-05-18
source: user_reported_process_miss
---

# LL-001 Harness Feature Evidence Closeout Miss

## Context

During RPA Harness v0 implementation, the work was intentionally split into F0-F14 capability slices and each slice was committed and pushed. The implementation also used tests and some subagent review.

However, the local AI-development Harness process was not followed completely: the work did not create or maintain a dedicated Feature page, Evidence record, Lesson/incident record, or Backlog state for F0-F14 before continuing through the feature sequence.

## Failure

The user reported:

```text
F01 到 F14 没有沉淀 Feature 等相关材料，没有遵从 harness 相关 skill。
```

The report is valid. Before this recovery:

- `docs/features` had `F001` only.
- `docs/evidence` had `EV-001` only.
- RPA Harness v0 had design docs and a plan, but no dedicated `F002` / `EV-002` closeout trail.
- The implementation plan had partial checkbox updates, but that did not satisfy the Harness Feature/Evidence lifecycle.

## Root Cause

The agent treated “feature slices independently committed and pushed” as sufficient progress control, and treated the implementation plan as the durable Harness anchor.

That was wrong. A plan is an execution route. It is not the same thing as:

- a Feature page that captures vision, acceptance, status, and residual risk;
- an Evidence record that captures verification and reviewer context;
- a Lesson when the process itself failed.

## Trigger

The failure became visible when the user reviewed the development trajectory and noticed that F01-F14 did not have corresponding Feature/Evidence materials despite explicit instructions to obey Harness skills.

## Impact

- Future agents could recover code history from commits, but not the original intent and acceptance state per capability slice.
- Residual asset findings could be mistaken for unrelated failures because no Feature-level Evidence connected them to Harness v0.
- The project risked building product Harness while violating its own AI-development Harness discipline.
- Review readiness was overstated because tests and commits existed but durable closeout was missing.

## Protection

For any future multi-feature or high-risk Harness/RPA work:

1. Create or update the Feature page before implementation starts.
2. Record the Vision Anchor, non-goals, feature sequence, acceptance criteria, and residual risks in the Feature page.
3. Record each slice's verification, commit hash, reviewer status, and residual risks in the Evidence record before moving to the next slice.
4. Treat an implementation plan as incomplete unless it links to Feature and Evidence records.
5. If any closeout category is missing, report `implementation done, harness closeout pending` instead of claiming completion or moving on.

## Project Rule Candidate

This lesson should be promoted to `AGENTS.md` because it changes future agent behavior across multi-feature Harness/RPA work:

- Scope: multi-feature Harness, RPA architecture, or other high-risk implementation sequences.
- Requirement: agents MUST create/update Feature and Evidence records before advancing between slices.
- Source: this Lesson.
- Rationale: prevents code-only progress from replacing recoverable project memory.

## Evidence

Recovery artifacts:

- Feature: `docs/features/F002-rpa-harness-v0.md`
- Evidence: `docs/evidence/EV-002-rpa-harness-v0.md`
- Backlog: `docs/BACKLOG.md`

## Status

Active. The immediate recovery creates the missing durable records, but F002 remains active until residual bootstrap asset findings are triaged and future slices prove they update Feature/Evidence before advancing.
