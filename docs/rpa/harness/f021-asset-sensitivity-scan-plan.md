# F021 Asset Sensitivity Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic RPA Harness asset sensitivity scanning, review packet integration, and sanitized replay contract reporting.

**Architecture:** Add a focused scanner module that reads asset text files and returns a structured report. Keep promotion governance separate: the scanner informs review and human confirmation, but does not promote assets. Review packet generation consumes the scanner report and renders a concise `Sensitivity Scan` section.

**Tech Stack:** Python, pytest, existing `backend.rpa.harness` CLI/report conventions.

---

### Task 1: Sensitivity Scanner Tests

**Files:**
- Create: `RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py`

- [ ] **Step 1: Write RED tests**

Create tests for raw secret/amount detection, sanitized replay contract preservation, and CLI output.

- [ ] **Step 2: Run RED tests**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py
```

Expected: fail because `backend.rpa.harness.sensitivity_scan` and CLI do not exist yet.

### Task 2: Scanner Module And CLI

**Files:**
- Create: `RpaClaw/backend/rpa/harness/sensitivity_scan.py`
- Create: `RpaClaw/backend/rpa/harness/run_asset_sensitivity_scan.py`

- [ ] **Step 1: Implement minimal scanner**

Implement deterministic regex/category scanning, report summary, per-finding records, recommended asset sensitivity, and sanitized replay contract status.

- [ ] **Step 2: Implement CLI**

Follow existing Harness CLI style and emit JSON via `emit_json_report`.

- [ ] **Step 3: Run scanner tests**

Run the focused scanner tests and keep the implementation minimal.

### Task 3: Review Packet Integration

**Files:**
- Modify: `RpaClaw/backend/rpa/harness/asset_review.py`
- Modify: `RpaClaw/backend/tests/test_rpa_harness_asset_review.py`

- [ ] **Step 1: Write RED review test**

Add a test proving `review.md` contains a `Sensitivity Scan` section with risk summary and sanitized replay status.

- [ ] **Step 2: Implement review rendering**

Call the scanner from `build_asset_review_packet()` and render concise markdown rows.

- [ ] **Step 3: Run review tests**

Run the focused review test.

### Task 4: Docs And Evidence

**Files:**
- Modify: `docs/rpa/harness/资产录制与审查最小流程.md`
- Modify: `docs/features/F021-rpa-harness-asset-sensitivity-scan.md`
- Modify: `docs/evidence/EV-021-rpa-harness-asset-sensitivity-scan.md`

- [ ] **Step 1: Document the command**

Add the scan command to the asset review flow and state that `--confirm-sensitivity` is a human confirmation based on evidence, not a scan.

- [ ] **Step 2: Record verification**

Update EV-021 with RED/GREEN commands and residual risk.

### Task 5: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused tests**

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py
```

- [ ] **Step 2: Run Harness knowledge check**

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

- [ ] **Step 3: Run diff check**

```powershell
git diff --check -- RpaClaw/backend/rpa/harness/sensitivity_scan.py RpaClaw/backend/rpa/harness/run_asset_sensitivity_scan.py RpaClaw/backend/rpa/harness/asset_review.py RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py docs/features/F021-rpa-harness-asset-sensitivity-scan.md docs/evidence/EV-021-rpa-harness-asset-sensitivity-scan.md docs/rpa/harness/f021-asset-sensitivity-scan-plan.md docs/rpa/harness/资产录制与审查最小流程.md
```
