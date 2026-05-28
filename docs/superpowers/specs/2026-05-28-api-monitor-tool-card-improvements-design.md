# API Monitor Tool Card Improvements

## Background

During tool recording in the API Monitor page, three issues were identified that affect usability and reliability.

## Issue 1: Intent Reason Not Displayed on Tool Cards

### Problem
When a tool is adopted or moved to the "not adopted" queue, the system-generated reason (from intent pruning or confidence scoring) is not visible on the tool card. The data already exists in `ApiToolDefinition.intent_reason` (copied from generation candidates during tool creation), but the frontend doesn't display it.

### Solution
**Frontend-only change.** In the expanded tool card detail section (adopted/not adopted areas), display `intent_reason` when present.

- Location: `ApiMonitorPage.vue`, in the tool card expanded detail area
- Display: Small text below confidence reasons, showing the intent pruning reason
- Only shown when `intent_reason` is non-empty

### Files
- `frontend/src/pages/ApiMonitorPage.vue` — add `intent_reason` display in expanded tool card section

## Issue 2: Intent Pruning Not Triggering During Recording

### Problem
During the recording flow, when the user fills in an intent before starting recording, generation candidates sometimes skip the intent pruning step and go directly to tool generation. This results in tools being generated that should have been filtered by intent relevance.

### Root Cause Analysis
The code path in `_process_captured_calls_for_generation` (manager.py ~L2883-2892) checks `candidate.status in ("pending", "stale", "failed")` before adding to the intent prune buffer. If `_upsert_generation_candidate` returns a candidate with a different status, the intent prune check is bypassed.

Additionally:
- The 3-second debounce on `_schedule_intent_prune_flush` can delay processing
- `_flush_intent_prune_buffer` discards the entire buffer if `session is None`
- Candidates updated from a previous recording session may retain non-pending status

### Solution
**Backend changes:**

1. **Ensure intent prune always runs when intent is set**: After `_upsert_generation_candidate`, if the candidate is new or has new data, force status to "pending" before the intent prune check, or move the intent prune check to a point where the candidate's status is guaranteed to be eligible.

2. **Add defensive flush in stop_recording**: In `_stop_recording_once`, after `_process_captured_calls_for_generation`, ensure `_flush_intent_prune_buffer` processes all buffered candidates even if some edge cases were missed.

3. **Add logging**: Log when candidates enter the intent prune buffer vs direct generation enqueue, to make debugging easier.

### Files
- `backend/rpa/api_monitor/manager.py` — fix intent prune trigger logic in `_process_captured_calls_for_generation`, add logging

## Issue 3: No Elapsed Time Display for Active Operations

### Problem
When a generation candidate is in an active state (generating, intent pruning, retrying) for an extended period, the user sees no feedback about how long the operation has been running. This makes the UI feel unresponsive.

### Solution
**Frontend-only change.** Add a live elapsed timer next to the status badge on generation candidate cards.

- Track when each candidate enters an active state using `updated_at` timestamp
- Display elapsed time in the status badge: "生成中 (12s)", "意图裁剪中 (5s)"
- Update every second via `setInterval`
- Stop timer when candidate reaches a non-active state
- Active states: `running`, `pending`, `intent_pruning`, `intent_prune_retrying`, `rate_limited`
- Format: show seconds when < 60s, "Xm Ys" when >= 60s

### Implementation
- Add a reactive map `candidateTimers: Map<string, number>` to track start timestamps
- Watch candidate status changes to update timer start points
- Use `setInterval` (1s) to refresh displayed elapsed times
- Clean up intervals on component unmount

### Files
- `frontend/src/pages/ApiMonitorPage.vue` — add timer display logic next to status badges on candidate cards

## Scope

- Frontend changes: `ApiMonitorPage.vue` only
- Backend changes: `manager.py` only
- No new API endpoints
- No database schema changes
- No i18n additions needed (Chinese-only labels already present)
