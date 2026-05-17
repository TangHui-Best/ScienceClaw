import json
from pathlib import Path

from backend.rpa.harness.blast_radius import build_blast_radius_report
from backend.rpa.harness.run_blast_radius import main as run_blast_radius_main


def _snapshot_report(*items: dict) -> dict:
    failed = len([item for item in items if item["status"] == "failed"])
    return {
        "summary": {"total": len(items), "passed": len(items) - failed, "failed": failed},
        "assets": list(items),
    }


def _compiler_report(*items: dict) -> dict:
    failed = len([item for item in items if item["status"] == "failed"])
    return {
        "summary": {"total": len(items), "passed": len(items) - failed, "failed": failed},
        "assets": list(items),
    }


def _catalog() -> dict:
    return {
        "schema_version": "rpa-harness-catalog-v0",
        "summary": {},
        "captures": [
            {
                "asset_id": "asset-active",
                "capture_scope": "selected_steps",
                "sop_intent": "Open a project from search results",
                "asset_status": "active",
                "sensitivity": "local-only",
            },
            {
                "asset_id": "asset-draft",
                "capture_scope": "selected_steps",
                "sop_intent": "Extract project details",
                "asset_status": "draft",
                "sensitivity": "local-only",
            },
        ],
        "steps": [
            {
                "asset_id": "asset-active",
                "step_index": 1,
                "step_id": "step-1",
                "step_intent": "Click ScienceClaw result",
                "runtime_status": "success",
                "before_url": "https://example.test/search",
                "after_url": "https://example.test/project/scienceclaw",
                "hosts": ["example.test"],
                "page_patterns": ["search-result", "card-list"],
            },
            {
                "asset_id": "asset-draft",
                "step_index": 2,
                "step_id": "step-2",
                "step_intent": "Extract repository metadata",
                "runtime_status": "success",
                "before_url": "https://docs.example.test/project/scienceclaw",
                "after_url": "",
                "hosts": ["docs.example.test"],
                "page_patterns": ["detail-page"],
            },
        ],
        "warnings": [],
    }


def test_blast_radius_marks_active_asset_failures_as_blocking():
    report = build_blast_radius_report(
        snapshot_report=_snapshot_report(
            {
                "asset_id": "asset-active",
                "step_index": 1,
                "step_id": "step-1",
                "step_intent": "Click ScienceClaw result",
                "page_patterns": ["search-result"],
                "status": "failed",
                "failure_category": "compact-snapshot-lost-signal",
                "missing_text": ["ScienceClaw"],
            }
        ),
        compiler_report=_compiler_report(
            {
                "asset_id": "asset-active",
                "step_index": 1,
                "step_id": "step-1",
                "step_intent": "Click ScienceClaw result",
                "page_patterns": ["card-list"],
                "status": "passed",
                "failure_category": "",
            }
        ),
        catalog=_catalog(),
    )

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["blocking_failed_steps"] == 1
    assert report["summary"]["warning_failed_steps"] == 0
    assert report["summary"]["affected_assets"] == ["asset-active"]
    assert report["summary"]["affected_page_patterns"] == ["card-list", "search-result"]
    assert report["summary"]["affected_hosts"] == ["example.test"]
    assert report["failures_by_category"] == {"compact-snapshot-lost-signal": 1}
    affected = report["affected_steps"][0]
    assert affected["asset_id"] == "asset-active"
    assert affected["asset_status"] == "active"
    assert affected["runner_failures"] == [
        {
            "runner": "snapshot",
            "status": "failed",
            "failure_category": "compact-snapshot-lost-signal",
        }
    ]


def test_blast_radius_reports_draft_asset_failures_as_warnings():
    report = build_blast_radius_report(
        snapshot_report=_snapshot_report(
            {
                "asset_id": "asset-draft",
                "step_index": 2,
                "step_id": "step-2",
                "step_intent": "Extract repository metadata",
                "page_patterns": ["detail-page"],
                "status": "passed",
                "failure_category": "",
            }
        ),
        compiler_report=_compiler_report(
            {
                "asset_id": "asset-draft",
                "step_index": 2,
                "step_id": "step-2",
                "step_intent": "Extract repository metadata",
                "page_patterns": ["detail-page"],
                "status": "failed",
                "failure_category": "compiler-dataflow-lost",
                "missing_dataflow_refs": ["_results['project']"],
            }
        ),
        catalog=_catalog(),
    )

    assert report["summary"]["status"] == "passed_with_warnings"
    assert report["summary"]["blocking_failed_steps"] == 0
    assert report["summary"]["warning_failed_steps"] == 1
    assert report["warnings"][0]["asset_id"] == "asset-draft"
    assert report["warnings"][0]["asset_status"] == "draft"


def test_blast_radius_requires_all_present_runner_sides_to_pass():
    report = build_blast_radius_report(
        snapshot_report=_snapshot_report(
            {
                "asset_id": "asset-active",
                "step_index": 1,
                "step_id": "step-1",
                "step_intent": "Click ScienceClaw result",
                "page_patterns": ["search-result"],
                "status": "passed",
                "failure_category": "",
            }
        ),
        compiler_report=_compiler_report(
            {
                "asset_id": "asset-active",
                "step_index": 1,
                "step_id": "step-1",
                "step_intent": "Click ScienceClaw result",
                "page_patterns": ["card-list"],
                "status": "failed",
                "failure_category": "compiler-hardcoded-observed-value",
                "hardcoded_values": ["ScienceClaw"],
            }
        ),
        catalog=_catalog(),
    )

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["checked_steps"] == 1
    assert report["summary"]["passed_steps"] == 0
    assert report["summary"]["failed_steps"] == 1
    assert report["affected_steps"][0]["runner_statuses"] == {
        "compiler": "failed",
        "snapshot": "passed",
    }


def test_blast_radius_flags_missing_runner_side_as_incomplete_evidence():
    report = build_blast_radius_report(
        snapshot_report=_snapshot_report(
            {
                "asset_id": "asset-active",
                "step_index": 1,
                "step_id": "step-1",
                "step_intent": "Click ScienceClaw result",
                "page_patterns": ["search-result"],
                "status": "passed",
                "failure_category": "",
            }
        ),
        compiler_report=None,
        catalog=_catalog(),
    )

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["blocking_failed_steps"] == 1
    assert report["failures_by_category"] == {"incomplete-runner-evidence": 1}
    assert report["affected_steps"][0]["runner_statuses"] == {
        "compiler": "missing",
        "snapshot": "passed",
    }
    assert report["affected_steps"][0]["runner_failures"] == [
        {
            "runner": "compiler",
            "status": "missing",
            "failure_category": "incomplete-runner-evidence",
        }
    ]


def test_blast_radius_cli_writes_report_file(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    compiler_path = tmp_path / "compiler.json"
    catalog_path = tmp_path / "catalog.json"
    output_path = tmp_path / "blast-radius.json"
    snapshot_path.write_text(
        json.dumps(
            _snapshot_report(
                {
                    "asset_id": "asset-active",
                    "step_index": 1,
                    "step_id": "step-1",
                    "step_intent": "Click ScienceClaw result",
                    "page_patterns": ["search-result"],
                    "status": "passed",
                    "failure_category": "",
                }
            )
        ),
        encoding="utf-8",
    )
    compiler_path.write_text(
        json.dumps(
            _compiler_report(
                {
                    "asset_id": "asset-active",
                    "step_index": 1,
                    "step_id": "step-1",
                    "step_intent": "Click ScienceClaw result",
                    "page_patterns": ["card-list"],
                    "status": "passed",
                    "failure_category": "",
                }
            )
        ),
        encoding="utf-8",
    )
    catalog_path.write_text(json.dumps(_catalog()), encoding="utf-8")

    exit_code = run_blast_radius_main(
        [
            "--snapshot-report",
            str(snapshot_path),
            "--compiler-report",
            str(compiler_path),
            "--catalog",
            str(catalog_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["status"] == "passed"
    assert report["summary"]["passed_steps"] == 1
