from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import inspect
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "rpa" / "snapshot_compression.py"
_SPEC = spec_from_file_location("snapshot_compression_structured_under_test", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

compact_recording_snapshot = _MODULE.compact_recording_snapshot


def _structured_view_snapshot() -> dict:
    return {
        "url": "https://example.test/grid",
        "title": "Grid",
        "content_nodes": [],
        "actionable_nodes": [],
        "containers": [],
        "frames": [],
        "table_views": [
            {
                "kind": "table_view",
                "title": "EDM Request",
                "title_source": "nearest_preceding_heading",
                "nearby_headings": ["EDM Request"],
                "framework_hint": "aui-grid",
                "row_count_observed": 10,
                "columns": [
                    {"index": 0, "column_id": "col_23", "header": "", "role": "row_index", "sample_values": ["1", "2"]},
                    {"index": 1, "column_id": "col_24", "header": "", "role": "selection", "sample_values": []},
                    {"index": 2, "column_id": "col_25", "header": "文件名称", "role": "file_link", "sample_values": ["File_189.xlsx"]},
                ],
                "rows": [
                    {
                        "index": 0,
                        "cells": [
                            {
                                "column_id": "col_23",
                                "column_index": 0,
                                "column_header": "",
                                "text": "1",
                                "value_kind": "number",
                                "actions": [],
                            },
                            {
                                "column_id": "col_25",
                                "column_index": 2,
                                "column_header": "文件名称",
                                "text": "File_189.xlsx",
                                "value_kind": "text",
                                "actions": [
                                    {
                                        "kind": "link",
                                        "label": "File_189.xlsx",
                                        "locator": {
                                            "method": "relative_css",
                                            "scope": "row",
                                            "value": "td[data-colid='col_25'] a",
                                        },
                                    }
                                ],
                            },
                        ],
                        "locator_hints": [{"kind": "playwright", "expression": "page.locator('tbody tr').nth(0)"}],
                    }
                ],
                "auxiliary_text": [{"kind": "empty_state", "text": "暂无数据", "outside_rows": True}],
            }
        ],
        "detail_views": [
            {
                "kind": "detail_view",
                "section_title": "采购信息",
                "fields": [
                    {
                        "label": "预计总金额(含税)",
                        "value": "100.00",
                        "data_prop": "amount",
                        "required": True,
                        "visible": True,
                        "value_kind": "number",
                    },
                    {
                        "label": "隐藏字段",
                        "value": "secret",
                        "data_prop": "hidden",
                        "required": False,
                        "visible": False,
                        "hidden_reason": "display_none",
                        "value_kind": "text",
                    },
                ],
            }
        ],
    }


def test_compact_recording_snapshot_preserves_structured_views():
    compact = compact_recording_snapshot(_structured_view_snapshot(), "点击第一行的文件名称", char_budget=100000)

    assert compact["mode"] == "clean_snapshot"
    assert compact["table_views"][0]["title"] == "EDM Request"
    assert compact["table_views"][0]["title_source"] == "nearest_preceding_heading"
    assert compact["table_views"][0]["nearby_headings"] == ["EDM Request"]
    assert compact["table_views"][0]["columns"][2]["header"] == "文件名称"
    assert compact["table_views"][0]["rows"][0]["cells"][1]["actions"][0]["locator"]["scope"] == "row"
    assert compact["table_views"][0]["auxiliary_text"][0]["outside_rows"] is True
    assert compact["detail_views"][0]["section_title"] == "采购信息"
    assert compact["detail_views"][0]["fields"][0]["data_prop"] == "amount"


def test_region_scoped_snapshot_keeps_selected_table_and_omits_outside_detail():
    snapshot = _structured_view_snapshot()
    snapshot["region_scope"] = {
        "region_id": "region-table",
        "frame_path": [],
        "frame_rect": {"x": 0, "y": 0, "width": 500, "height": 300},
    }
    snapshot["table_views"][0]["scope_relation"] = "inside_region"
    snapshot["detail_views"][0]["scope_relation"] = "outside_context"

    compact = compact_recording_snapshot(snapshot, "extract selected table", char_budget=1)

    assert compact["mode"] == "region_scoped_snapshot"
    assert len(compact["table_views"]) == 1
    assert compact["table_views"][0]["title"] == "EDM Request"
    assert compact["table_views"][0]["columns"][2]["header"] == snapshot["table_views"][0]["columns"][2]["header"]
    assert compact["detail_views"] == []


def test_region_scoped_snapshot_keeps_only_selected_table_rows_with_headers():
    snapshot = _structured_view_snapshot()
    snapshot["region_scope"] = {
        "region_id": "region-table-rows",
        "frame_path": [],
        "frame_rect": {"x": 0, "y": 120, "width": 500, "height": 80},
    }
    snapshot["table_views"][0]["scope_relation"] = "inside_region"
    snapshot["table_views"][0]["selected_row_indexes"] = [1, 2]
    snapshot["table_views"][0]["rows"].extend(
        [
            {
                "index": 1,
                "scope_relation": "inside_region",
                "cells": [
                    {
                        "column_id": "col_23",
                        "column_index": 0,
                        "column_header": "",
                        "text": "2",
                        "value_kind": "number",
                        "actions": [],
                    },
                    {
                        "column_id": "col_25",
                        "column_index": 2,
                        "column_header": "鏂囦欢鍚嶇О",
                        "text": "File_190.xlsx",
                        "value_kind": "text",
                        "actions": [],
                    },
                ],
                "locator_hints": [{"kind": "playwright", "expression": "page.locator('tbody tr').nth(1)"}],
            },
            {
                "index": 2,
                "scope_relation": "inside_region",
                "cells": [
                    {
                        "column_id": "col_23",
                        "column_index": 0,
                        "column_header": "",
                        "text": "3",
                        "value_kind": "number",
                        "actions": [],
                    },
                    {
                        "column_id": "col_25",
                        "column_index": 2,
                        "column_header": "鏂囦欢鍚嶇О",
                        "text": "File_191.xlsx",
                        "value_kind": "text",
                        "actions": [],
                    },
                ],
                "locator_hints": [{"kind": "playwright", "expression": "page.locator('tbody tr').nth(2)"}],
            },
        ]
    )

    compact = compact_recording_snapshot(snapshot, "process selected table rows", char_budget=1)

    table = compact["table_views"][0]
    assert table["columns"][2]["header"] == snapshot["table_views"][0]["columns"][2]["header"]
    assert [row["index"] for row in table["rows"]] == [1, 2]
    assert all(row.get("scope_relation") == "inside_region" for row in table["rows"])
    assert "File_189.xlsx" not in str(table["rows"])


def test_region_scoped_snapshot_keeps_selected_form_controls_only():
    snapshot = {
        "url": "https://example.test/form",
        "title": "Scoped Form",
        "content_nodes": [
            {
                "node_id": "selected-label",
                "container_id": "selected-form",
                "semantic_kind": "text",
                "text": "Search Term:",
                "bbox": {"x": 20, "y": 40, "width": 90, "height": 20},
                "scope_relation": "inside_region",
                "element_snapshot": {"tag": "label", "text": "Search Term:"},
            },
            {
                "node_id": "outside-label",
                "container_id": "outside-form",
                "semantic_kind": "text",
                "text": "Invoice Total:",
                "bbox": {"x": 20, "y": 140, "width": 90, "height": 20},
                "scope_relation": "outside_context",
                "element_snapshot": {"tag": "label", "text": "Invoice Total:"},
            },
        ],
        "actionable_nodes": [
            {
                "node_id": "selected-input",
                "container_id": "selected-form",
                "tag": "input",
                "role": "textbox",
                "name": "Search Term",
                "text": "",
                "bbox": {"x": 120, "y": 40, "width": 200, "height": 24},
                "scope_relation": "inside_region",
                "locator": {"method": "role", "role": "textbox", "name": "Search Term"},
                "element_snapshot": {"tag": "input", "text": ""},
                "is_visible": True,
                "is_enabled": True,
                "hit_test_ok": True,
                "action_kinds": ["fill"],
            },
            {
                "node_id": "outside-input",
                "container_id": "outside-form",
                "tag": "input",
                "role": "textbox",
                "name": "Invoice Total",
                "text": "",
                "bbox": {"x": 120, "y": 140, "width": 200, "height": 24},
                "scope_relation": "outside_context",
                "locator": {"method": "role", "role": "textbox", "name": "Invoice Total"},
                "element_snapshot": {"tag": "input", "text": ""},
                "is_visible": True,
                "is_enabled": True,
                "hit_test_ok": True,
                "action_kinds": ["fill"],
            },
        ],
        "containers": [
            {
                "container_id": "selected-form",
                "container_kind": "form_section",
                "name": "Selected Filters",
                "summary": "Search Term",
            },
            {
                "container_id": "outside-form",
                "container_kind": "form_section",
                "name": "Outside Totals",
                "summary": "Invoice Total",
            },
        ],
        "frames": [],
        "table_views": [],
        "detail_views": [],
        "region_scope": {
            "region_id": "region-form",
            "frame_path": [],
            "frame_rect": {"x": 10, "y": 30, "width": 340, "height": 60},
        },
    }

    compact = compact_recording_snapshot(snapshot, "fill the search term", char_budget=1)

    assert compact["mode"] == "region_scoped_snapshot"
    assert [view["title"] for view in compact["form_views"]] == ["Selected Filters"]
    assert compact["form_views"][0]["fields"][0]["label"] == "Search Term"
    assert "Invoice Total" not in str(compact["form_views"])


def test_region_scoped_snapshot_keeps_only_selected_detail_fields_with_section_title():
    snapshot = _structured_view_snapshot()
    snapshot["region_scope"] = {
        "region_id": "region-detail-field",
        "frame_path": [],
        "frame_rect": {"x": 0, "y": 0, "width": 500, "height": 120},
    }
    snapshot["detail_views"][0]["scope_relation"] = "inside_region"
    snapshot["detail_views"][0]["fields"][0]["scope_relation"] = "inside_region"
    snapshot["detail_views"][0]["fields"][1]["scope_relation"] = "outside_context"

    compact = compact_recording_snapshot(snapshot, "extract selected field", char_budget=1)

    assert compact["detail_views"][0]["section_title"] == snapshot["detail_views"][0]["section_title"]
    assert [field["data_prop"] for field in compact["detail_views"][0]["fields"]] == ["amount"]
    assert "secret" not in str(compact["detail_views"])


def test_default_structured_snapshot_budget_is_60000():
    signature = inspect.signature(compact_recording_snapshot)
    assert signature.parameters["char_budget"].default == 60000

    snapshot = _structured_view_snapshot()
    snapshot["detail_views"][0]["fields"].extend(
        {
            "label": f"扩展字段{index}",
            "value": "这是一个用于验证默认结构化快照预算的中等长度字段值",
            "data_prop": f"extra_{index}",
            "required": False,
            "visible": True,
            "value_kind": "text",
        }
        for index in range(120)
    )

    compact = compact_recording_snapshot(snapshot, "提取采购信息")

    assert compact["mode"] == "clean_snapshot"
