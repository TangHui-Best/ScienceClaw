import asyncio
import importlib
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

import backend.rpa.recording_runtime_agent as recording_runtime_agent
from backend.rpa.recording_runtime_agent import (
    RecordingRuntimeAgent,
    RECORDING_RUNTIME_SYSTEM_PROMPT,
    _classify_recording_failure,
    _build_detail_extract_plan,
    _ensure_expected_effect,
    _expected_effect,
    _instruction_is_detail_extract_only,
    _normalize_generated_playwright_code,
    _parse_json_object,
    _resolve_recording_snapshot_debug_dir,
    _resolve_recording_snapshot_debug_path,
    _snapshot_plan_fields,
)
from backend.rpa.trace_skill_compiler import TraceSkillCompiler
from backend.rpa.trace_models import RPAPageState


class _FakePage:
    url = "https://example.test/start"

    def __init__(self):
        self._event_handlers = {}

    async def title(self):
        return "Example"

    def locator(self, _selector):
        return _FakeLocator()

    async def goto(self, url, wait_until=None):
        self.url = url

    async def wait_for_load_state(self, _state):
        return None

    def on(self, event, handler):
        self._event_handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        handlers = self._event_handlers.get(event) or []
        self._event_handlers[event] = [item for item in handlers if item is not handler]

    async def trigger_download(self, filename):
        download = SimpleNamespace(suggested_filename=filename)
        for handler in list(self._event_handlers.get("download") or []):
            result = handler(download)
            if hasattr(result, "__await__"):
                await result

    def trigger_download_later(self, filename, delay=0.05):
        async def emit():
            await asyncio.sleep(delay)
            await self.trigger_download(filename)

        asyncio.create_task(emit())


class _FakeLocator:
    def nth(self, _index):
        return self

    async def click(self):
        return None

    async def fill(self, _value):
        return None


class _FakeListPage(_FakePage):
    def __init__(self):
        self.url = "https://github.com/trending"
        self.clicked = []
        self._selectors = {
            "h2.lh-condensed a": ["alpha / one", "beta / two", "gamma / three"],
            "a.download-link": ["Download", "Download", "Download"],
        }

    def locator(self, selector):
        return _FakeListLocator(self, selector, self._selectors.get(selector, []))


class _FakeListLocator:
    def __init__(self, page, selector, values, index=None):
        self.page = page
        self.selector = selector
        self.values = values
        self.index = index

    def nth(self, index):
        return _FakeListLocator(self.page, self.selector, self.values, index)

    async def count(self):
        return len(self.values)

    async def inner_text(self):
        return self.values[self.index or 0]

    async def click(self):
        self.page.clicked.append((self.selector, self.index or 0))
        if self.selector == "h2.lh-condensed a":
            self.page.url = f"https://github.com/{self.values[self.index or 0].replace(' / ', '/')}"


class _FakeNavigatedPage(_FakePage):
    url = "https://github.com/HKUDS/RAG-Anything"

    async def title(self):
        return "GitHub - HKUDS/RAG-Anything"


@pytest.fixture(autouse=True)
def _disable_recording_snapshot_debug_by_default(monkeypatch):
    monkeypatch.delenv("RPA_RECORDING_DEBUG_SNAPSHOT_DIR", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "backend.config",
        SimpleNamespace(settings=SimpleNamespace(rpa_recording_debug_snapshot_dir="")),
    )


def _find_region_with_pair(snapshot, label, value):
    for region in snapshot.get("expanded_regions") or []:
        if region.get("kind") != "label_value_group":
            continue
        for pair in (region.get("evidence") or {}).get("pairs") or []:
            if pair.get("label") == label and pair.get("value") == value:
                return region
    return None


def _ordinal_snapshot():
    containers = []
    actionable_nodes = []
    repos = ["alpha / one", "beta / two", "gamma / three"]
    for index, repo in enumerate(repos):
        container_id = f"repo-{index}"
        containers.append(
            {
                "container_id": container_id,
                "container_kind": "card_group",
                "name": repo,
                "bbox": {"x": 10, "y": 100 + index * 90, "width": 800, "height": 80},
            }
        )
        actionable_nodes.append(
            {
                "node_id": f"title-{index}",
                "container_id": container_id,
                "role": "link",
                "name": repo,
                "text": repo,
                "href": f"/{repo.replace(' / ', '/')}",
                "collection_container_selector": "article",
                "collection_item_selector": "h2.lh-condensed a",
                "collection_item_count": len(repos),
            }
        )
        actionable_nodes.append(
            {
                "node_id": f"download-{index}",
                "container_id": container_id,
                "role": "link",
                "name": "Download",
                "text": "Download",
                "href": f"/{repo.replace(' / ', '/')}/archive.zip",
                "collection_container_selector": "article",
                "collection_item_selector": "a.download-link",
                "collection_item_count": len(repos),
            }
        )
    return {
        "url": "https://github.com/trending",
        "title": "Trending repositories",
        "frames": [],
        "content_nodes": [],
        "containers": containers,
        "actionable_nodes": actionable_nodes,
    }


def _ordinal_frame_collection_snapshot():
    return {
        "url": "https://github.com/trending",
        "title": "Trending repositories",
        "actionable_nodes": [],
        "content_nodes": [],
        "containers": [],
        "frames": [
            {
                "frame_path": [],
                "frame_hint": "main document",
                "elements": [],
                "collections": [
                    {
                        "kind": "repeated_items",
                        "item_count": 5,
                        "container_hint": {"locator": {"method": "css", "value": "li"}},
                        "item_hint": {
                            "locator": {"method": "css", "value": "button.js-details-target"},
                            "role": "button",
                        },
                        "items": [
                            {"index": 3, "tag": "button", "role": "button", "name": "Platform"},
                            {"index": 4, "tag": "button", "role": "button", "name": "Solutions"},
                            {"index": 5, "tag": "button", "role": "button", "name": "Resources"},
                            {"index": 6, "tag": "button", "role": "button", "name": "Open Source"},
                            {"index": 7, "tag": "button", "role": "button", "name": "Enterprise"},
                        ],
                    },
                    {
                        "kind": "repeated_items",
                        "item_count": 12,
                        "container_hint": {
                            "locator": {
                                "method": "css",
                                "value": "div.position-relative.container-lg div div article div",
                            }
                        },
                        "item_hint": {"locator": {"method": "css", "value": "a"}, "role": "link"},
                        "items": [
                            {"index": 26, "tag": "a", "role": "link", "name": "7,684"},
                            {"index": 27, "tag": "a", "role": "link", "name": "1,199"},
                            {"index": 35, "tag": "a", "role": "link", "name": "4,864"},
                            {"index": 36, "tag": "a", "role": "link", "name": "402"},
                        ],
                    },
                    {
                        "kind": "repeated_items",
                        "item_count": 12,
                        "container_hint": {
                            "locator": {
                                "method": "css",
                                "value": "div.position-relative.container-lg div div article",
                            }
                        },
                        "item_hint": {
                            "locator": {"method": "css", "value": "h2.lh-condensed a"},
                            "role": "link",
                        },
                        "items": [
                            {"index": 25, "tag": "a", "role": "link", "name": "Alishahryar1 / free-claude-code"},
                            {"index": 34, "tag": "a", "role": "link", "name": "huggingface / ml-intern"},
                            {"index": 42, "tag": "a", "role": "link", "name": "google / osv-scanner"},
                        ],
                    },
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_run_python_fill_accepts_action_evidence_from_output():
    page = _FakePage()
    result = await _ensure_expected_effect(
        page=page,
        instruction="fill the previous title into the PR summary field",
        plan={"action_type": "run_python", "expected_effect": "fill"},
        result={
            "success": True,
            "output": {
                "action_performed": True,
                "action_type": "fill",
                "filled_value": "Example",
            },
        },
        before=RPAPageState(url=page.url, title="Example"),
    )

    assert result["success"] is True
    assert result["effect"]["action_performed"] is True
    assert result["effect"]["type"] == "fill"


def test_ordinal_overlay_builds_relative_first_item_name_plan():
    build_plan = getattr(recording_runtime_agent, "_build_ordinal_overlay_plan")

    plan = build_plan("get the first project name", _ordinal_snapshot())

    assert plan is not None
    assert plan["expected_effect"] == "extract"
    assert "page.locator('h2.lh-condensed a').nth(0)" in plan["code"]
    assert "alpha / one" not in plan["code"]


def test_ordinal_overlay_builds_first_n_names_plan():
    build_plan = getattr(recording_runtime_agent, "_build_ordinal_overlay_plan")

    plan = build_plan("get the first 2 project names", _ordinal_snapshot())

    assert plan is not None
    assert plan["expected_effect"] == "extract"
    assert "_limit = min(2, await _items.count())" in plan["code"]
    assert "return _result" in plan["code"]


def test_ordinal_overlay_uses_frame_collection_when_actionable_nodes_are_unannotated():
    build_plan = getattr(recording_runtime_agent, "_build_ordinal_overlay_plan")

    plan = build_plan("获取第一个项目的名称", _ordinal_frame_collection_snapshot())

    assert plan is not None
    assert "page.locator('h2.lh-condensed a').nth(0)" in plan["code"]
    assert "Alishahryar1 / free-claude-code" not in plan["code"]


def test_ordinal_overlay_builds_second_download_plan():
    build_plan = getattr(recording_runtime_agent, "_build_ordinal_overlay_plan")

    plan = build_plan("点击第二项名字进行下载", _ordinal_snapshot())

    assert plan is not None
    assert plan["expected_effect"] == "none"
    assert "page.locator('a.download-link').nth(1).click()" in plan["code"]
    assert "beta / two" not in plan["code"]


def test_ordinal_overlay_falls_back_for_identical_action_only_collection():
    build_plan = getattr(recording_runtime_agent, "_build_ordinal_overlay_plan")
    snapshot = _ordinal_snapshot()
    snapshot["actionable_nodes"] = [
        node for node in snapshot["actionable_nodes"] if str(node.get("node_id", "")).startswith("download-")
    ]

    plan = build_plan("click the first item", snapshot)

    assert plan is None


def test_ordinal_overlay_falls_back_for_semantic_selection():
    build_plan = getattr(recording_runtime_agent, "_build_ordinal_overlay_plan")

    plan = build_plan("open the project most related to python", _ordinal_snapshot())

    assert plan is None


def _table_view_snapshot():
    return {
        "url": "https://example.test/grid",
        "title": "Grid",
        "frames": [],
        "actionable_nodes": [],
        "content_nodes": [],
        "containers": [],
        "table_views": [
            {
                "kind": "table_view",
                "framework_hint": "structured-grid",
                "columns": [
                    {"index": 0, "column_id": "col_23", "header": "", "role": "row_index"},
                    {"index": 1, "column_id": "col_24", "header": "", "role": "selection"},
                    {"index": 2, "column_id": "col_25", "header": "文件名称", "role": "file_link"},
                    {"index": 3, "column_id": "col_28", "header": "导出状态", "role": "status"},
                ],
                "rows": [
                    {
                        "index": 0,
                        "cells": [
                            {
                                "column_id": "col_25",
                                "column_index": 2,
                                "column_header": "文件名称",
                                "text": "File_189.xlsx",
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
                            {"column_id": "col_28", "column_index": 3, "column_header": "导出状态", "text": "FINISH", "actions": []},
                        ],
                        "locator_hints": [{"kind": "playwright", "expression": "page.locator('table[data-role=\"grid-body\"] tbody tr').nth(0)"}],
                    },
                    {
                        "index": 1,
                        "cells": [
                            {
                                "column_id": "col_25",
                                "column_index": 2,
                                "column_header": "文件名称",
                                "text": "File_380.xlsx",
                                "actions": [
                                    {
                                        "kind": "link",
                                        "label": "File_380.xlsx",
                                        "locator": {
                                            "method": "relative_css",
                                            "scope": "row",
                                            "value": "td[data-colid='col_25'] a",
                                        },
                                    }
                                ],
                            },
                            {"column_id": "col_28", "column_index": 3, "column_header": "导出状态", "text": "FINISH", "actions": []},
                        ],
                        "locator_hints": [{"kind": "playwright", "expression": "page.locator('table[data-role=\"grid-body\"] tbody tr').nth(1)"}],
                    },
                ],
            }
        ],
        "detail_views": [],
    }


def test_table_ordinal_lane_clicks_first_row_named_column_link():
    build_plan = getattr(recording_runtime_agent, "_build_table_ordinal_overlay_plan")

    plan = build_plan("点击第一行的文件名称", _table_view_snapshot())

    assert plan is not None
    assert plan["table_ordinal_overlay"] is True
    assert "table[data-role=\"grid-body\"] tbody tr" in plan["code"]
    assert "td[data-colid='col_25'] a" in plan["code"]
    assert "File_189.xlsx" not in plan["code"]


def test_table_ordinal_lane_extracts_second_row_status():
    build_plan = getattr(recording_runtime_agent, "_build_table_ordinal_overlay_plan")

    plan = build_plan("提取第二行的导出状态", _table_view_snapshot())

    assert plan is not None
    assert "nth(1)" in plan["code"]
    assert "td[data-colid='col_28']" in plan["code"]
    assert plan["expected_effect"] == "extract"


def test_table_ordinal_lane_falls_back_without_column_match():
    build_plan = getattr(recording_runtime_agent, "_build_table_ordinal_overlay_plan")

    plan = build_plan("点击第一行的审批按钮", _table_view_snapshot())

    assert plan is None


def _named_multi_table_view_snapshot():
    snapshot = _table_view_snapshot()
    edm_table = snapshot["table_views"][0]
    edm_table["title"] = "EDM Request"
    edm_table["title_source"] = "nearest_preceding_heading"
    edm_table["nearby_headings"] = ["EDM Request"]
    edm_table["columns"][2]["column_id"] = "col_2"
    edm_table["columns"][2]["header"] = "File Name"
    edm_table["columns"][3]["column_id"] = "col_3"
    edm_table["columns"][3]["header"] = "Export Status"
    edm_table["rows"][0]["cells"][0]["column_id"] = "col_2"
    edm_table["rows"][0]["cells"][0]["column_header"] = "File Name"
    edm_table["rows"][0]["cells"][0]["text"] = "EquipmentConfigurationLevelSplitDataSheet_17728130.xlsx"
    edm_table["rows"][0]["cells"][0]["actions"][0]["locator"]["value"] = 'td[data-colid="col_2"] a'
    edm_table["rows"][0]["locator_hints"] = [{"kind": "playwright", "expression": "page.locator('tbody tr').nth(0)"}]
    edm_table["rows"][1]["cells"][0]["column_id"] = "col_2"
    edm_table["rows"][1]["cells"][0]["column_header"] = "File Name"
    edm_table["rows"][1]["locator_hints"] = [{"kind": "playwright", "expression": "page.locator('tbody tr').nth(1)"}]
    jalor_table = {
        **edm_table,
        "title": "Jalor Request",
        "nearby_headings": ["Jalor Request"],
    }
    snapshot["table_views"] = [jalor_table, edm_table]
    snapshot["actionable_nodes"] = [
        {
            "role": "link",
            "name": "Home",
            "text": "Home",
            "collection_item_selector": "div a",
            "collection_item_count": 6,
        },
        {
            "role": "link",
            "name": "Request",
            "text": "Request",
            "collection_item_selector": "div a",
            "collection_item_count": 6,
        },
    ]
    return snapshot


def test_table_ordinal_lane_scopes_named_table_without_observed_row_text():
    build_plan = getattr(recording_runtime_agent, "_build_table_ordinal_overlay_plan")

    plan = build_plan("获取EDM Request表格中第一行的File Name", _named_multi_table_view_snapshot())

    assert plan is not None
    assert plan["table_ordinal_overlay"] is True
    assert "get_by_text('EDM Request', exact=True)" in plan["code"]
    assert "following::table" in plan["code"]
    assert "col_2" in plan["code"]
    assert "div a" not in plan["code"]
    assert "EquipmentConfigurationLevelSplitDataSheet_17728130.xlsx" not in plan["code"]


def test_table_ordinal_lane_extracts_first_n_rows_as_headered_records():
    build_plan = getattr(recording_runtime_agent, "_build_table_ordinal_overlay_plan")

    plan = build_plan("获取EDM Request表格中前三行的信息", _named_multi_table_view_snapshot())

    assert plan is not None
    assert plan["table_ordinal_overlay"] is True
    assert plan["expected_effect"] == "extract"
    assert "get_by_text('EDM Request', exact=True)" in plan["code"]
    assert "_limit = min(3, await _rows.count())" in plan["code"]
    assert "'File Name'" in plan["code"]
    assert "'Export Status'" in plan["code"]


@pytest.mark.asyncio
async def test_recording_runtime_agent_uses_ordinal_overlay_without_planner(monkeypatch):
    async def fake_build_page_snapshot(*_args, **_kwargs):
        return _ordinal_snapshot()

    async def planner(_payload):
        raise AssertionError("planner should not be called for high-confidence ordinal tasks")

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    page = _FakeListPage()
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction="get the first project name",
        runtime_results={},
    )

    assert result.success is True
    assert result.output == "alpha / one"
    assert "page.locator('h2.lh-condensed a').nth(0)" in result.trace.ai_execution.code
    assert "alpha / one" not in result.trace.ai_execution.code


def test_backend_rpa_package_import_is_lazy():
    module = importlib.import_module("backend.rpa")

    assert "rpa_manager" not in module.__dict__
    assert "RPASession" not in module.__dict__
    assert "RPAStep" not in module.__dict__
    assert "cdp_connector" not in module.__dict__
    assert module.__all__ == ["rpa_manager", "RPASession", "RPAStep", "cdp_connector"]


def test_recording_runtime_agent_module_import_does_not_require_llm_stack(monkeypatch):
    module_path = Path(__file__).resolve().parents[1] / "rpa" / "recording_runtime_agent.py"
    blocked_modules = [
        "langchain_core",
        "langchain_core.messages",
        "backend.deepagent",
        "backend.deepagent.engine",
    ]
    for name in blocked_modules:
        monkeypatch.setitem(sys.modules, name, None)

    spec = importlib.util.spec_from_file_location(
        "backend.rpa.recording_runtime_agent_lazy_import_test",
        module_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "RecordingRuntimeAgent")


def test_recording_runtime_prompt_defines_result_return_contract():
    assert "`results` 是普通 Python dict" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "只能通过 `return`" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "禁止调用 `results.set(...)`" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "`output_key` 只是给后置 trace compiler 使用的元数据" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "internal_ref" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "不是 DOM id、CSS selector 或 Playwright locator" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "locator_hints" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "action_performed" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "filled_value" in RECORDING_RUNTIME_SYSTEM_PROMPT


def test_recording_runtime_prompt_prefers_structured_snapshot_views():
    assert "extract_snapshot" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "table_views" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "detail_views" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "form_views" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "row-relative" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "column-relative" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "Do not turn summary text into placeholder" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "Do not use observed row text as the primary selector when the instruction is ordinal" in RECORDING_RUNTIME_SYSTEM_PROMPT


def test_recording_runtime_prompt_does_not_advertise_table_snapshot_extracts():
    assert "snapshot.detail_views or snapshot.table_views" not in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "fields/rows" not in RECORDING_RUNTIME_SYSTEM_PROMPT


def test_recording_runtime_prompt_requires_terminal_business_evidence():
    assert "business-visible terminal condition" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "do not unconditionally add a new row" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "scope field locators to the dialog/form container" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "structured snapshot.detail_views fields as the source of truth" in RECORDING_RUNTIME_SYSTEM_PROMPT


def test_recording_runtime_prompt_uses_bounded_waits_and_avoids_callable_locator_names():
    assert "short bounded waits" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "Do not pass Python lambda" in RECORDING_RUNTIME_SYSTEM_PROMPT


def test_recording_runtime_prompt_includes_replay_metadata_contract():
    assert "input_bindings" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "output_bindings" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "postcondition" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "in-page filter/search forms" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "intercepts pointer events" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "Do not click unnamed increment/decrement controls repeatedly" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "open a specific record" in RECORDING_RUNTIME_SYSTEM_PROMPT
    assert "Do not return `downloaded: false`" in RECORDING_RUNTIME_SYSTEM_PROMPT


def test_recording_snapshot_debug_dir_falls_back_to_backend_settings(monkeypatch):
    monkeypatch.delenv("RPA_RECORDING_DEBUG_SNAPSHOT_DIR", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "backend.config",
        SimpleNamespace(settings=SimpleNamespace(rpa_recording_debug_snapshot_dir="data/from-settings")),
    )

    assert _resolve_recording_snapshot_debug_dir() == "data/from-settings"


def test_recording_snapshot_debug_path_resolves_relative_path_from_project_root():
    resolved = _resolve_recording_snapshot_debug_path("data/rpa_recording_snapshots")

    assert resolved == Path(__file__).resolve().parents[3] / "data" / "rpa_recording_snapshots"


@pytest.mark.asyncio
async def test_recording_runtime_agent_accepts_successful_python_plan():
    plans = [
        {
            "description": "Extract title",
            "action_type": "run_python",
            "output_key": "page_title",
            "code": "async def run(page, results):\n    return {'title': await page.title()}",
        }
    ]

    async def planner(_payload):
        return plans.pop(0)

    agent = RecordingRuntimeAgent(planner=planner)
    result = await agent.run(page=_FakePage(), instruction="extract title", runtime_results={})

    assert result.success is True
    assert result.trace.output_key == "page_title"
    assert result.trace.output == {"title": "Example"}
    assert result.trace.ai_execution.repair_attempted is False

@pytest.mark.asyncio
async def test_recording_runtime_agent_persists_runtime_ai_preserve_signal():
    async def planner(_payload):
        return {
            "description": "Select the closest matching project",
            "action_type": "run_python",
            "expected_effect": "click",
            "output_key": "selected_project",
            "preserve_runtime_ai": True,
            "semantic_intent": "select_best_matching_candidate",
            "code": (
                "async def run(page, results):\n"
                "    await page.locator('a.project').nth(0).click()\n"
                "    return {'action_performed': True, 'action_type': 'click', 'target': 'alpha'}"
            ),
        }

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="open the closest matching project",
        runtime_results={},
    )

    assert result.success is True
    assert result.trace.signals["runtime_ai"]["preserve"] is True
    assert result.trace.signals["runtime_ai"]["reason"] == "select_best_matching_candidate"


def test_recording_runtime_agent_persists_replay_metadata_into_compilable_trace(monkeypatch):
    async def fake_build_page_snapshot(*_args, **_kwargs):
        return {
            "table_views": [
                {
                    "columns": [{"header": "Invoice"}, {"header": "Status"}],
                    "rows": [
                        {
                            "cells": [
                                {"column_header": "Invoice", "text": "INV-001"},
                                {"column_header": "Status", "text": "Submitted"},
                            ]
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    async def planner(_payload):
        return {
            "description": "Search invoice and verify row",
            "action_type": "run_python",
            "expected_effect": "fill",
            "output_key": "invoice_search",
            "input_bindings": {
                "invoice_number": {
                    "source": "user_param",
                    "default": "INV-001",
                    "classification": "user_param",
                }
            },
            "output_bindings": {
                "invoice_number": {"path": "invoice_number"},
            },
            "postcondition": {
                "kind": "table_row_exists",
                "source": "observed",
                "table_headers": ["Invoice", "Status"],
                "key": {"Invoice": "{{invoice_number}}"},
                "expect": {"Status": "Submitted"},
            },
            "code": (
                "async def run(page, results):\n"
                "    await page.locator('input[name=invoice]').fill('INV-001')\n"
                "    return {'action_performed': True, 'action_type': 'fill', 'invoice_number': 'INV-001'}"
            ),
        }

    result = asyncio.run(
        RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
            instruction="search invoice INV-001 and verify submitted row",
            runtime_results={},
        )
    )

    assert result.success is True
    assert result.trace.input_bindings["invoice_number"]["default"] == "INV-001"
    assert result.trace.output_bindings["invoice_number"]["path"] == "invoice_number"
    assert result.trace.postcondition["kind"] == "table_row_exists"

    script = TraceSkillCompiler().generate_script([result.trace], is_local=True)
    assert "kwargs.get('invoice_number', 'INV-001')" in script
    assert "await _find_table_row_by_headers" in script
    assert ".fill('INV-001')" not in script


def test_recording_runtime_agent_ignores_untrusted_planner_postcondition():
    async def planner(_payload):
        return {
            "description": "Search invoice",
            "action_type": "run_python",
            "expected_effect": "fill",
            "output_key": "invoice_search",
            "postcondition": {
                "kind": "table_row_exists",
                "table_headers": ["Invoice", "Status"],
                "key": {"Invoice": "INV-001"},
                "expect": {"Status": "Done"},
            },
            "code": (
                "async def run(page, results):\n"
                "    await page.locator('input[name=invoice]').fill('INV-001')\n"
                "    return {'action_performed': True, 'action_type': 'fill', 'invoice_number': 'INV-001'}"
            ),
        }

    result = asyncio.run(
        RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
            instruction="search invoice INV-001",
            runtime_results={},
        )
    )

    assert result.success is True
    assert result.trace.postcondition == {}


def test_recording_runtime_agent_ignores_postcondition_without_snapshot_evidence():
    async def planner(_payload):
        return {
            "description": "Search invoice",
            "action_type": "run_python",
            "expected_effect": "fill",
            "output_key": "invoice_search",
            "input_bindings": {
                "invoice_number": {
                    "source": "user_param",
                    "default": "INV-001",
                    "classification": "user_param",
                }
            },
            "postcondition": {
                "kind": "table_row_exists",
                "source": "observed",
                "table_headers": ["Header"],
                "key": {"Header": "{{invoice_number}}"},
                "expect": {"Status": "Done"},
            },
            "code": (
                "async def run(page, results):\n"
                "    await page.locator('input[name=invoice]').fill('INV-001')\n"
                "    return {'action_performed': True, 'action_type': 'fill', 'invoice_number': 'INV-001'}"
            ),
        }

    result = asyncio.run(
        RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
            instruction="search invoice INV-001",
            runtime_results={},
        )
    )

    assert result.success is True
    assert result.trace.postcondition == {}


def test_recording_runtime_agent_accepts_extract_snapshot_plan(monkeypatch):
    async def fake_build_page_snapshot(_page, _build_frame_path):
        return {
            "url": "https://example.test/detail",
            "title": "Detail",
            "frames": [],
            "actionable_nodes": [],
            "content_nodes": [],
            "containers": [],
            "detail_views": [],
        }

    async def planner(_payload):
        return {
            "description": "Extract procurement info",
            "action_type": "extract_snapshot",
            "expected_effect": "extract",
            "output_key": "procurement_info",
            "source": "detail_views",
            "section_title": "采购信息",
            "fields": [
                {
                    "label": "预计总金额 (含税）",
                    "value": "100.00",
                    "data_prop": "2652409177955720363",
                    "visible": True,
                    "value_kind": "number",
                },
                {
                    "label": "预计到货时间 (UTC+08:00)",
                    "value": "",
                    "data_prop": "7757927649859165361",
                    "visible": False,
                    "value_kind": "empty",
                },
            ],
        }

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    result = asyncio.run(
        RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
        instruction="提取采购信息中的内容",
            runtime_results={},
        )
    )

    assert result.success is True
    assert result.output == {"预计总金额 (含税）": "100.00"}
    assert result.trace.ai_execution.language == "snapshot"
    assert "extract_snapshot" in result.trace.ai_execution.code
    assert "预计总金额 (含税）" in result.trace.ai_execution.code
    assert result.trace.signals["extract_snapshot"]["source"] == "detail_views"
    assert result.trace.signals["extract_snapshot"]["fields"][0]["data_prop"] == "2652409177955720363"


def test_recording_runtime_agent_enriches_snapshot_extract_with_replay_evidence(monkeypatch):
    async def fake_build_page_snapshot(_page, _build_frame_path):
        return {
            "url": "https://github.com/mattpocock/skills",
            "title": "Repository",
            "frames": [],
            "actionable_nodes": [
                {
                    "role": "link",
                    "tag": "a",
                    "name": "Star 32.2k",
                    "text": "Star 32.2k",
                    "element_snapshot": {"tag": "a", "text": "Star 32.2k"},
                }
            ],
            "content_nodes": [
                {
                    "semantic_kind": "text",
                    "tag": "a",
                    "text": "32.2k stars",
                    "element_snapshot": {"tag": "a", "text": "32.2k stars"},
                },
                {
                    "semantic_kind": "text",
                    "tag": "a",
                    "text": "2.5k forks",
                    "element_snapshot": {"tag": "a", "text": "2.5k forks"},
                },
            ],
            "containers": [],
            "detail_views": [],
        }

    async def planner(_payload):
        return {
            "description": "Extract repository summary",
            "action_type": "extract_snapshot",
            "expected_effect": "extract",
            "output_key": "repo_basic_info",
            "source": "visible_page",
            "fields": [
                {"label": "project_name", "value": "mattpocock/skills", "visible": True},
                {"label": "star_count", "value": "32.2k", "visible": True},
                {"label": "fork_count", "value": "2.5k", "visible": True},
            ],
        }

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    result = asyncio.run(
        RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
            instruction="Extract repository project name, stars, and forks",
            runtime_results={},
        )
    )

    fields = {field["label"]: field for field in result.trace.signals["extract_snapshot"]["fields"]}

    assert fields["project_name"]["url_extraction"] == {
        "kind": "url_path_join",
        "start": 0,
        "count": 2,
        "separator": "/",
    }
    assert fields["star_count"]["text_pattern"]["suffix"] == "stars"
    assert fields["fork_count"]["text_pattern"]["suffix"] == "forks"
    assert fields["star_count"]["text_pattern"]["value"] == "32.2k"
    assert fields["fork_count"]["text_pattern"]["value"] == "2.5k"


@pytest.mark.asyncio
async def test_recording_runtime_agent_preserves_extract_snapshot_frame_path(monkeypatch):
    async def fake_build_page_snapshot(_page, _build_frame_path):
        return {
            "url": "https://example.test/detail",
            "title": "Detail",
            "frames": [],
            "actionable_nodes": [],
            "content_nodes": [],
            "containers": [],
            "detail_views": [],
        }

    async def planner(_payload):
        return {
            "description": "Extract iframe detail",
            "action_type": "extract_snapshot",
            "expected_effect": "extract",
            "output_key": "iframe_detail",
            "source": "detail_views",
            "section_title": "Detail",
            "frame_path": ["iframe[title='detail']"],
            "fields": [
                {
                    "label": "Amount",
                    "value": "100.00",
                    "data_prop": "amount",
                    "visible": True,
                    "value_kind": "number",
                }
            ],
        }

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="extract iframe detail",
        runtime_results={},
    )

    assert result.success is True
    assert result.trace.signals["extract_snapshot"]["frame_path"] == ["iframe[title='detail']"]


@pytest.mark.asyncio
async def test_recording_runtime_agent_attaches_locator_stability_metadata_when_available():
    async def planner(_payload):
        return {
            "description": "Open stable action menu",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "opened_menu",
            "code": (
                "async def run(page, results):\n"
                "    await page.locator('[data-testid=\"menu-btn-a1b2c3d4\"]').click()\n"
                "    return {'opened': True}"
            ),
        }

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="inspect the action menu button",
        runtime_results={},
    )

    assert result.success is True
    metadata = result.trace.locator_stability
    assert metadata is not None
    assert metadata.primary_locator["method"] == "css"
    assert metadata.unstable_signals[0]["attribute"] == "data-testid"


@pytest.mark.asyncio
async def test_recording_runtime_agent_keeps_trace_success_when_no_locator_stability_metadata_is_found():
    async def planner(_payload):
        return {
            "description": "Return summary",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "summary",
            "code": "async def run(page, results):\n    return {'summary': 'ok'}",
        }

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="summarize page",
        runtime_results={},
    )

    assert result.success is True
    assert result.trace.locator_stability is None


@pytest.mark.asyncio
async def test_recording_runtime_agent_extracts_stable_self_and_anchor_signals_from_snapshot(monkeypatch):
    snapshot = {
        "url": "https://example.test/dashboard",
        "title": "Dashboard",
        "actionable_nodes": [
            {
                "role": "button",
                "name": "Open menu",
                "text": "Open menu",
                "locator": {"method": "role", "role": "button", "name": "Open menu"},
                "container": {"title": "Quarterly Report"},
            }
        ],
        "content_nodes": [],
        "containers": [],
        "frames": [],
    }

    async def fake_build_page_snapshot(_page, _build_frame_path):
        return snapshot

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    async def planner(_payload):
        return {
            "description": "Inspect report menu",
            "action_type": "run_python",
            "expected_effect": "extract",
            "code": (
                "async def run(page, results):\n"
                "    await page.locator('[data-testid=\"menu-btn-a1b2c3d4\"]').click()\n"
                "    return {'opened': True}"
            ),
        }

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="inspect the report menu button",
        runtime_results={},
    )

    assert result.success is True
    metadata = result.trace.locator_stability
    assert metadata is not None
    assert metadata.stable_self_signals["role"] == "button"
    assert metadata.stable_self_signals["name"] == "Open menu"
    assert metadata.stable_anchor_signals["title"] == "Quarterly Report"
    assert metadata.alternate_locators[0].locator == {
        "method": "role",
        "role": "button",
        "name": "Open menu",
    }


@pytest.mark.asyncio
async def test_ensure_expected_effect_accepts_run_python_click_when_url_changes():
    page = _FakeNavigatedPage()
    result = await _ensure_expected_effect(
        page=page,
        instruction="click the third project",
        plan={
            "action_type": "run_python",
            "expected_effect": "click",
            "code": 'async def run(page, results):\n    await page.get_by_role("link", name="HKUDS / RAG-Anything").click()',
        },
        result={"success": True, "output": None},
        before=RPAPageState(url="https://github.com/trending", title="Trending repositories on GitHub today · GitHub"),
    )

    assert result["success"] is True
    assert result["effect"]["type"] == "click"
    assert result["effect"]["action_performed"] is True
    assert result["effect"]["observed_url_change"] is True
    assert result["effect"]["url"] == "https://github.com/HKUDS/RAG-Anything"


@pytest.mark.asyncio
async def test_ensure_expected_effect_accepts_mixed_with_action_evidence_without_url_change():
    page = _FakePage()
    before = RPAPageState(url=page.url, title="Example")

    result = await _ensure_expected_effect(
        page=page,
        instruction="fill the form and collect the confirmation",
        plan={"action_type": "run_python", "expected_effect": "mixed"},
        result={"success": True, "effect": {"type": "fill", "action_performed": True}},
        before=before,
    )

    assert result["success"] is True
    assert page.url == before.url
    assert result["effect"]["action_performed"] is True


@pytest.mark.asyncio
async def test_ensure_expected_effect_accepts_mixed_with_structured_output_without_url_change():
    page = _FakePage()
    before = RPAPageState(url=page.url, title="Example")

    result = await _ensure_expected_effect(
        page=page,
        instruction="submit the search and capture the selected row",
        plan={"action_type": "run_python", "expected_effect": "mixed"},
        result={"success": True, "output": {"selected_row": {"name": "alpha", "status": "ready"}}},
        before=before,
    )

    assert result["success"] is True
    assert page.url == before.url
    assert result["output"]["selected_row"]["name"] == "alpha"


@pytest.mark.asyncio
async def test_ensure_expected_effect_rejects_mixed_error_shaped_output_without_url_change():
    page = _FakePage()
    before = RPAPageState(url=page.url, title="Example")

    result = await _ensure_expected_effect(
        page=page,
        instruction="submit the form",
        plan={"action_type": "run_python", "expected_effect": "mixed"},
        result={"success": True, "output": {"error": "submit button was not found"}},
        before=before,
    )

    assert result["success"] is False
    assert "Expected navigation effect" in result["error"]


def test_ensure_expected_effect_rejects_visible_error_output_even_when_url_changes():
    page = _FakeNavigatedPage()

    result = asyncio.run(
        _ensure_expected_effect(
            page=page,
            instruction="submit the form and create the record",
            plan={"action_type": "run_python", "expected_effect": "mixed"},
            result={"success": True, "output": {"body_text_excerpt": "Record not found\nPlease complete required fields"}},
            before=RPAPageState(url="https://example.test/form", title="Form"),
        )
    )

    assert result["success"] is False
    assert "visible error" in result["error"]


def test_ensure_expected_effect_rejects_nonterminal_download_output():
    page = _FakePage()
    before = RPAPageState(url=page.url, title="Example")

    result = asyncio.run(
        _ensure_expected_effect(
            page=page,
            instruction="generate the report and download it",
            plan={"action_type": "run_python", "expected_effect": "mixed"},
            result={"success": True, "output": {"task_state": "not_confirmed_complete", "downloaded": False}},
            before=before,
        )
    )

    assert result["success"] is False
    assert "terminal success evidence" in result["error"]


@pytest.mark.asyncio
async def test_ensure_expected_effect_accepts_mixed_with_download_signal_without_url_change():
    page = _FakePage()
    before = RPAPageState(url=page.url, title="Example")

    result = await _ensure_expected_effect(
        page=page,
        instruction="generate and download the report",
        plan={"action_type": "run_python", "expected_effect": "mixed"},
        result={"success": True, "signals": {"download": {"filename": "report.xlsx", "count": 1}}},
        before=before,
    )

    assert result["success"] is True
    assert page.url == before.url
    assert result["signals"]["download"]["filename"] == "report.xlsx"


def test_expected_effect_treats_extract_snapshot_as_extract_even_when_plan_says_navigate():
    assert (
        _expected_effect(
            {
                "action_type": "extract_snapshot",
                "expected_effect": "navigate",
            },
            "打开详情并提取字段",
        )
        == "extract"
    )


@pytest.mark.asyncio
async def test_ensure_expected_effect_accepts_extract_snapshot_signal_even_if_plan_says_navigate():
    page = _FakePage()

    result = await _ensure_expected_effect(
        page=page,
        instruction="打开详情并提取字段",
        plan={"action_type": "extract_snapshot", "expected_effect": "navigate"},
        result={
            "success": True,
            "output": {"合同编号": "CT-001"},
            "signals": {"extract_snapshot": {"source": "detail_views"}},
        },
        before=RPAPageState(url=page.url, title="Example"),
    )

    assert result["success"] is True
    assert result["output"] == {"合同编号": "CT-001"}


def test_compact_snapshot_preserves_active_modal_dialogs():
    compact = recording_runtime_agent._compact_snapshot(
        {
            "url": "https://example.test/orders",
            "title": "Orders",
            "frames": [],
            "content_nodes": [],
            "actionable_nodes": [],
            "containers": [],
            "table_views": [],
            "detail_views": [],
            "modal_dialogs": [
                {
                    "title": "Approve order",
                    "role": "dialog",
                    "modal": True,
                    "fields": [{"label": "Comment", "value": ""}],
                    "actions": [
                        {
                            "label": "Approve",
                            "locator": {"method": "testid", "value": "approve"},
                        }
                    ],
                }
            ],
        },
        "approve the order in the dialog",
    )

    assert compact["modal_dialogs"][0]["title"] == "Approve order"
    assert compact["modal_dialogs"][0]["fields"][0]["label"] == "Comment"
    assert compact["modal_dialogs"][0]["actions"][0]["label"] == "Approve"


def test_detail_extract_plan_uses_visible_detail_fields_for_extract_requests():
    plan = _build_detail_extract_plan(
        "提取当前合同详情字段",
        {
            "detail_views": [
                {
                    "section_title": "合同详情",
                    "frame_path": [],
                    "fields": [
                        {"label": "合同编号", "value": "CT-001", "visible": True},
                        {"label": "内部标识", "value": "hidden", "visible": False},
                    ],
                }
            ]
        },
    )

    assert plan is not None
    assert plan["action_type"] == "extract_snapshot"
    assert plan["expected_effect"] == "extract"
    assert plan["fields"][0]["label"] == "合同编号"
    assert plan["fields"][0]["value"] == "CT-001"
    assert plan["fields"][0]["visible"] is True
    assert len(plan["fields"]) == 1


def test_empty_search_plan_extracts_query_token_and_returns_run_python():
    pytest.skip("empty-result search is now planner-driven, not a deterministic shortcut")
    plan = _build_empty_search_plan(
        "搜索不存在的编号 NO-SUCH-RECORD-001，确认没有匹配结果",
        {"table_views": [{"rows": [{"cells": []}]}]},
    )

    assert plan is not None
    assert plan["action_type"] == "run_python"
    assert plan["expected_effect"] == "mixed"
    assert "NO-SUCH-RECORD-001" in plan["code"]
    assert "没有匹配结果" in plan["code"]


def test_normalize_generated_playwright_code_repairs_common_python_api_typo():
    assert (
        _normalize_generated_playwright_code("await page.get_by_testid('submit').click()")
        == "await page.get_by_test_id('submit').click()"
    )


def test_recording_runtime_main_path_has_no_domain_specific_terms():
    source = Path(recording_runtime_agent.__file__).read_text(encoding="utf-8")
    domain_terms = [
        "采购申请",
        "采购订单",
        "合同编号",
        "供应商",
        "报表中心",
    ]

    for term in domain_terms:
        assert term not in source


def test_recording_failure_classifies_active_overlay_interception():
    analysis = _classify_recording_failure(
        'Locator.click: Timeout 60000ms exceeded. <div role="dialog"> intercepts pointer events'
    )

    assert analysis["type"] == "active_overlay_intercepted_click"
    assert "visible dialog" in analysis["hint"]


def test_recording_failure_classifies_non_editable_fill_target():
    analysis = _classify_recording_failure(
        "Locator.fill: Error: Element is not an <input>, <textarea>, <select> or [contenteditable]"
    )

    assert analysis["type"] == "non_editable_fill_target"


def test_recording_failure_classifies_number_input_text_fill():
    analysis = _classify_recording_failure(
        "Locator.fill: Error: Cannot type text into input[type=number]\n"
        "  - locator resolved to <input type=\"number\" role=\"spinbutton\"/>"
    )

    assert analysis["type"] == "numeric_input_text_mismatch"
    assert "number input" in analysis["hint"]


def test_runtime_agent_uses_planner_for_search_empty_result_semantics(monkeypatch):
    calls = []

    async def fake_snapshot(_page):
        return {
            "url": "https://example.test/items",
            "title": "Items",
            "table_views": [
                {
                    "columns": [{"header": "Number"}],
                    "rows": [],
                }
            ],
        }

    async def planner(payload):
        calls.append(payload)
        return {
            "description": "LLM semantic plan",
            "action_type": "run_python",
            "expected_effect": "extract",
            "allow_empty_output": False,
            "output_key": "llm_result",
            "code": "async def run(page, results):\n    return {'ok': True}",
        }

    async def executor(_page, plan, _runtime_results):
        return {"success": True, "output": {"used": plan["output_key"]}}

    monkeypatch.setattr(recording_runtime_agent, "_safe_page_snapshot", fake_snapshot)

    result = asyncio.run(
        RecordingRuntimeAgent(planner=planner, executor=executor).run(
            page=_FakePage(),
            instruction="Search for ABC-404 and confirm that there is no matching record.",
        )
    )

    assert result.success is True
    assert calls
    assert result.output == {"used": "llm_result"}


@pytest.mark.asyncio
async def test_ensure_expected_effect_accepts_run_python_fill_with_structured_output():
    page = _FakePage()
    before = RPAPageState(url=page.url, title="Example")

    result = await _ensure_expected_effect(
        page=page,
        instruction="fill and submit the dialog",
        plan={
            "action_type": "run_python",
            "expected_effect": "fill",
            "code": "async def run(page, results):\n    await page.locator('input').fill('ok')\n    return {'submitted': True}",
        },
        result={"success": True, "output": {"submitted": True}},
        before=before,
    )

    assert result["success"] is True
    assert result["effect"]["action_performed"] is True
    assert result["effect"]["generic_evidence"] == "structured_output"


@pytest.mark.asyncio
async def test_recording_runtime_agent_repairs_once_after_failure():
    calls = []

    async def planner(payload):
        calls.append(payload)
        if "repair" not in payload:
            return {
                "description": "Broken",
                "action_type": "run_python",
                "code": "async def run(page, results):\n    raise RuntimeError('boom')",
            }
        return {
            "description": "Fixed",
            "action_type": "run_python",
            "output_key": "fixed",
            "code": "async def run(page, results):\n    return {'ok': True}",
        }

    agent = RecordingRuntimeAgent(planner=planner)
    result = await agent.run(page=_FakePage(), instruction="do it", runtime_results={})

    assert result.success is True
    assert len(calls) == 2
    assert result.trace.ai_execution.repair_attempted is True
    assert result.diagnostics[0].message == "boom"


@pytest.mark.asyncio
async def test_recording_runtime_agent_repair_payload_has_traceback_and_omits_unknown_failure_analysis():
    calls = []

    async def planner(payload):
        calls.append(payload)
        if "repair" not in payload:
            return {
                "description": "Broken result write",
                "action_type": "run_python",
                "expected_effect": "extract",
                "code": (
                    "async def run(page, results):\n"
                    "    details = [{'name': 'paper'}]\n"
                    "    results.set('purchase_details', details)\n"
                    "    return details"
                ),
            }
        return {
            "description": "Return extracted result",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "purchase_details",
            "code": (
                "async def run(page, results):\n"
                "    details = [{'name': 'paper'}]\n"
                "    return details"
            ),
        }

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="extract purchase details",
        runtime_results={},
    )

    repair_payload = calls[1]["repair"]
    assert result.success is True
    assert "failure_analysis" not in repair_payload
    assert repair_payload["error"] == "'dict' object has no attribute 'set'"
    assert repair_payload["error_type"] == "AttributeError"
    assert "Traceback (most recent call last)" in repair_payload["traceback"]
    assert "results.set('purchase_details', details)" in repair_payload["traceback"]
    assert result.diagnostics[0].message == repair_payload["error"]


@pytest.mark.asyncio
async def test_recording_runtime_agent_sends_advisory_failure_hint_to_repair_planner():
    calls = []

    async def planner(payload):
        calls.append(payload)
        if "repair" not in payload:
            return {
                "description": "Wait for brittle issue selector",
                "action_type": "run_python",
                "expected_effect": "extract",
                "code": (
                    "async def run(page, results):\n"
                    "    raise TimeoutError('Page.wait_for_selector: Timeout 15000ms exceeded waiting for locator(\"[data-testid=issue-list]\")')"
                ),
            }
        return {
            "description": "Scan issue links",
            "action_type": "run_python",
            "expected_effect": "none",
            "output_key": "latest_issue",
            "code": "async def run(page, results):\n    return {'latest_issue_title': 'Latest issue'}",
        }

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="find the latest issue title",
        runtime_results={},
    )

    repair_payload = calls[1]["repair"]
    assert result.success is True
    assert result.diagnostics[0].message.startswith("Page.wait_for_selector")
    assert repair_payload["error"].startswith("Page.wait_for_selector")
    assert repair_payload["failure_analysis"]["type"] == "selector_timeout"
    assert "hint" in repair_payload["failure_analysis"]
    assert "confidence" not in repair_payload["failure_analysis"]
    assert result.diagnostics[0].raw["failure_analysis"]["type"] == "selector_timeout"


def test_recording_runtime_agent_does_not_preserve_failed_browser_mutation_attempts():
    plans = [
        {
            "description": "Submit form",
            "action_type": "run_python",
            "expected_effect": "mixed",
            "code": "async def run(page, results):\n    await page.get_by_role('button', name='Submit').click()\n    raise RuntimeError('terminal state not observed')",
        },
        {
            "description": "Verify result",
            "action_type": "run_python",
            "expected_effect": "none",
            "output_key": "created_record",
            "code": "async def run(page, results):\n    return {'id': 'ID-1'}",
        },
    ]
    calls = []

    async def planner(_payload):
        return plans[len(calls)]

    async def executor(_page, plan, _runtime_results):
        calls.append(plan)
        if len(calls) == 1:
            return {"success": False, "error": "terminal state not observed", "output": {"submitted": True}}
        return {"success": True, "output": {"id": "ID-1"}}

    result = asyncio.run(
        RecordingRuntimeAgent(planner=planner, executor=executor).run(
            page=_FakePage(),
            instruction="submit the form and verify the created record",
            runtime_results={},
        )
    )

    assert result.success is True
    assert len(result.traces) == 1
    assert "recovered_attempt" not in result.traces[0].signals
    assert result.trace == result.traces[0]


def test_recording_runtime_agent_repairs_invalid_planner_output():
    calls = []

    async def planner(payload):
        calls.append(payload)
        if "repair" not in payload:
            raise ValueError("Recording planner must return Python code defining async def run(page, results)")
        return {
            "description": "Verify result after planner repair",
            "action_type": "run_python",
            "expected_effect": "none",
            "output_key": "verified",
            "code": "async def run(page, results):\n    return {'status': 'ok'}",
        }

    result = asyncio.run(
        RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
            instruction="click submit and verify result",
            runtime_results={},
        )
    )

    assert result.success is True
    assert len(calls) == 2
    assert calls[1]["repair"]["error"].startswith("Recording planner must return Python code")
    assert result.diagnostics[0].raw["error_type"] == "ValueError"


def test_detail_extract_intent_excludes_open_filter_navigation_tasks():
    assert _instruction_is_detail_extract_only("提取当前详情页中的供应商和金额")
    assert not _instruction_is_detail_extract_only("筛选合同并打开详情页读取供应商和金额")
    assert not _instruction_is_detail_extract_only("navigate to the contract page and read the amount")


def test_detail_extract_intent_does_not_strip_context_or_negative_guardrails():
    instruction = """
    你正在执行 RPA 任务。系统已经完成登录，并已导航到起始页面。
    请只执行下面的业务任务，不要重新登录，不要把打开当前页面当作完成。
    当前已经在详情页。请从页面字段中提取供应商、金额和有效期，并在回答中列出。
    """

    assert not _instruction_is_detail_extract_only(instruction)
    assert _instruction_is_detail_extract_only("当前已经在详情页。请从页面字段中提取供应商、金额和有效期，并在回答中列出。")


def test_detail_extract_plan_combines_multiple_detail_views():
    snapshot = {
        "detail_views": [
            {"section_title": "基本信息", "fields": [{"label": "编号", "value": "A-1", "visible": True}]},
            {"section_title": "供应商", "fields": [{"label": "名称", "value": "Acme", "visible": True}]},
        ]
    }

    plan = _build_detail_extract_plan("提取当前详情页中的字段", snapshot)

    assert plan is not None
    assert [field["label"] for field in plan["fields"]] == ["编号", "名称"]
    assert plan["section_title"] == "基本信息 / 供应商"


def test_normalize_generated_playwright_code_removes_unsupported_filter_kwargs():
    code = (
        "async def run(page, results):\n"
        "    loc = page.locator('input').filter(has_attribute='placeholder', has_text='')\n"
        "    other = page.locator('input').filter(has_attribute='disabled')\n"
    )

    normalized = _normalize_generated_playwright_code(code)

    assert "has_attribute" not in normalized
    assert ".filter(has_text='')" in normalized
    assert "other = page.locator('input')" in normalized


@pytest.mark.asyncio
async def test_recording_runtime_agent_payload_includes_structured_regions(monkeypatch):
    calls = []

    async def planner(payload):
        calls.append(payload)
        return {
            "description": "Extract buyer and value",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "buyer_info",
            "code": "async def run(page, results):\n    return {'buyer': '李雨晨', 'amount': '1000'}",
        }

    snapshot = {
        "url": "https://example.test/detail",
        "title": "Detail Page",
        "content_nodes": [
            {
                "node_id": "label-1",
                "container_id": "detail-card",
                "semantic_kind": "label",
                "role": "label",
                "text": "购买人",
                "bbox": {"x": 20, "y": 20, "width": 80, "height": 20},
                "locator": {"method": "text", "value": "购买人"},
                "element_snapshot": {"tag": "label", "text": "购买人"},
            },
            {
                "node_id": "value-1",
                "container_id": "detail-card",
                "semantic_kind": "field_value",
                "role": "",
                "text": "李雨晨",
                "bbox": {"x": 120, "y": 20, "width": 80, "height": 20},
                "locator": {"method": "text", "value": "李雨晨"},
                "element_snapshot": {"tag": "span", "text": "李雨晨", "class": "field-value"},
            },
        ],
        "containers": [
            {
                "container_id": "detail-card",
                "frame_path": [],
                "container_kind": "card",
                "name": "单据基本信息",
                "summary": "",
                "child_actionable_ids": [],
                "child_content_ids": ["label-1", "value-1"],
            }
        ],
        "actionable_nodes": [],
        "frames": [],
    }

    async def fake_build_page_snapshot(_page, _build_frame_path):
        return snapshot

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="提取单据基本信息中的购买人和金额",
        runtime_results={},
    )

    assert result.success is True
    region = _find_region_with_pair(calls[0]["snapshot"], "购买人", "李雨晨")
    assert region is not None
    assert "region_catalogue" in calls[0]["snapshot"]


@pytest.mark.asyncio
async def test_recording_runtime_agent_forwards_structured_views_to_planner(monkeypatch):
    snapshot = {
        "url": "https://example.test/grid",
        "title": "Grid",
        "frames": [],
        "actionable_nodes": [],
        "content_nodes": [],
        "containers": [],
        "table_views": [
            {
                "kind": "table_view",
                "columns": [{"index": 0, "column_id": "col_25", "header": "文件名称", "role": "file_link"}],
                "rows": [
                    {
                        "index": 0,
                        "cells": [
                            {
                                "column_id": "col_25",
                                "column_header": "文件名称",
                                "text": "File_189.xlsx",
                                "actions": [],
                            }
                        ],
                    }
                ],
            }
        ],
        "detail_views": [],
    }
    calls = []

    async def fake_build_page_snapshot(_page, _build_frame_path):
        return snapshot

    async def fake_planner(payload):
        calls.append(payload)
        return {
            "description": "Extract grid",
            "action_type": "run_python",
            "expected_effect": "extract",
            "code": "async def run(page, results):\n    return 'ok'",
            "output_key": "grid_result",
        }

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    agent = RecordingRuntimeAgent(planner=fake_planner)
    result = await agent.run(page=_FakePage(), instruction="提取第一行文件名称", runtime_results={})

    assert result.success is True
    assert calls[0]["snapshot"]["table_views"][0]["columns"][0]["header"] == "文件名称"


@pytest.mark.asyncio
async def test_recording_runtime_agent_forwards_instruction_into_snapshot_compaction(monkeypatch):
    compact_calls = []
    planner_calls = []

    def fake_compact_recording_snapshot(snapshot, instruction, *, char_budget=20000):
        compact_calls.append(
            {
                "instruction": instruction,
                "snapshot_url": snapshot.get("url"),
                "char_budget": char_budget,
            }
        )
        return {
            "mode": "clean_snapshot",
            "url": snapshot.get("url", ""),
            "title": snapshot.get("title", ""),
            "expanded_regions": [],
            "sampled_regions": [],
            "region_catalogue": [],
        }

    async def planner(payload):
        planner_calls.append(payload)
        if "repair" not in payload:
            return {
                "description": "Broken first pass",
                "action_type": "run_python",
                "code": "async def run(page, results):\n    raise RuntimeError('boom')",
            }
        return {
            "description": "Repair pass",
            "action_type": "run_python",
            "output_key": "done",
            "code": "async def run(page, results):\n    return {'ok': True}",
        }

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.compact_recording_snapshot", fake_compact_recording_snapshot)
    async def fake_build_page_snapshot(*_args, **_kwargs):
        return {
            "url": "https://example.test/detail",
            "title": "Detail Page",
            "frames": [],
        }

    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="提取单据基本信息中的购买人和金额",
        runtime_results={},
    )

    assert result.success is True
    assert [call["instruction"] for call in compact_calls] == [
        "提取单据基本信息中的购买人和金额",
        "提取单据基本信息中的购买人和金额",
    ]
    assert planner_calls[0]["snapshot"]["url"] == "https://example.test/detail"
    assert planner_calls[1]["repair"]["snapshot_after_failure"]["url"] == "https://example.test/detail"


@pytest.mark.asyncio
async def test_recording_runtime_agent_dumps_initial_snapshot_when_debug_dir_is_enabled(monkeypatch):
    raw_snapshot = {
        "url": "https://github.com/trending",
        "title": "Trending",
        "content_nodes": [{"text": "Claude Code SDK"}],
        "actionable_nodes": [{"role": "link", "text": "anthropics/claude-code"}],
        "containers": [],
        "frames": [],
    }
    compact_snapshot = {
        "mode": "clean_snapshot",
        "url": "https://github.com/trending",
        "title": "Trending",
        "expanded_regions": [{"title": "Claude Code SDK"}],
        "sampled_regions": [],
        "region_catalogue": [],
    }

    async def fake_build_page_snapshot(*_args, **_kwargs):
        return raw_snapshot

    def fake_compact_recording_snapshot(_snapshot, _instruction, *, char_budget=20000):
        return compact_snapshot

    async def planner(_payload):
        return {
            "description": "Open related project",
            "action_type": "run_python",
            "expected_effect": "none",
            "code": "async def run(page, results):\n    return {'opened': True}",
        }

    debug_dir = Path(__file__).resolve().parents[1] / "recording_debug_test_output"
    debug_dir.mkdir(exist_ok=True)
    for pattern in ("*-snapshot-*.json", "*-attempt-*.json", "*-code-*.py", "snapshot-*.json", "attempt-*.json", "code-*.py", "recording-snapshot-*.json", "recording-attempt-*.json", "recording-code-*.py"):
        for existing in debug_dir.glob(pattern):
            existing.unlink()

    monkeypatch.setenv("RPA_RECORDING_DEBUG_SNAPSHOT_DIR", str(debug_dir))
    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)
    monkeypatch.setattr("backend.rpa.recording_runtime_agent.compact_recording_snapshot", fake_compact_recording_snapshot)

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="打开和Claudecode最相关的项目",
        runtime_results={"previous": "value"},
        debug_context={"session_id": "sess-debug-1"},
    )

    session_debug_dir = debug_dir / "sess-debug-1"
    files = list(session_debug_dir.glob("*-snapshot-*.json"))
    assert result.success is True
    assert len(files) == 1
    assert not list(debug_dir.glob("*-snapshot-*.json"))
    assert files[0].name == "001-initial-snapshot-打开和Claudecode最相关的项目.json"

    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["stage"] == "initial"
    assert payload["debug_context"]["session_id"] == "sess-debug-1"
    assert payload["instruction"] == "打开和Claudecode最相关的项目"
    assert payload["raw_snapshot"] == raw_snapshot
    assert payload["compact_snapshot"] == compact_snapshot
    assert payload["snapshot_metrics"]["raw_snapshot"]["content_node_count"] == 1
    assert payload["snapshot_metrics"]["compact_snapshot"]["mode"] == "clean_snapshot"
    assert payload["snapshot_comparison"]["classification"] == "present_in_both"
    assert payload["runtime_results"] == {"previous": "value"}
    for pattern in ("*-snapshot-*.json", "*-attempt-*.json", "*-code-*.py", "snapshot-*.json", "attempt-*.json", "code-*.py", "recording-snapshot-*.json", "recording-attempt-*.json", "recording-code-*.py"):
        for file in session_debug_dir.glob(pattern):
            file.unlink()
    if session_debug_dir.exists():
        session_debug_dir.rmdir()


@pytest.mark.asyncio
async def test_recording_runtime_agent_dumps_repair_snapshot_after_first_failure(monkeypatch):
    calls = []
    raw_snapshots = [
        {
            "url": "https://github.com/trending",
            "title": "Trending",
            "content_nodes": [{"text": "Claude Code"}],
            "actionable_nodes": [],
            "containers": [],
            "frames": [],
        },
        {
            "url": "https://github.com/search",
            "title": "Search",
            "content_nodes": [],
            "actionable_nodes": [],
            "containers": [],
            "frames": [],
        },
    ]

    async def fake_build_page_snapshot(*_args, **_kwargs):
        return raw_snapshots.pop(0)

    def fake_compact_recording_snapshot(snapshot, _instruction, *, char_budget=20000):
        return {
            "mode": "clean_snapshot",
            "url": snapshot.get("url", ""),
            "title": snapshot.get("title", ""),
            "expanded_regions": [],
            "sampled_regions": [],
            "region_catalogue": [],
        }

    async def planner(payload):
        calls.append(payload)
        if "repair" not in payload:
            return {
                "description": "Broken search strategy",
                "action_type": "run_python",
                "expected_effect": "none",
                "code": (
                    "async def run(page, results):\n"
                    "    raise TimeoutError('Locator.click: Timeout 60000ms exceeded\\n"
                    "Call log:\\n  - waiting for get_by_placeholder(\"Search or jump to…\")')"
                ),
            }
        return {
            "description": "Recovered",
            "action_type": "run_python",
            "expected_effect": "none",
            "code": "async def run(page, results):\n    return {'ok': True}",
        }

    debug_dir = Path(__file__).resolve().parents[1] / "recording_debug_test_output"
    debug_dir.mkdir(exist_ok=True)
    for pattern in ("*-snapshot-*.json", "*-attempt-*.json", "*-code-*.py", "snapshot-*.json", "attempt-*.json", "code-*.py", "recording-snapshot-*.json", "recording-attempt-*.json", "recording-code-*.py"):
        for existing in debug_dir.glob(pattern):
            existing.unlink()

    monkeypatch.setenv("RPA_RECORDING_DEBUG_SNAPSHOT_DIR", str(debug_dir))
    monkeypatch.setattr("backend.rpa.recording_runtime_agent.build_page_snapshot", fake_build_page_snapshot)
    monkeypatch.setattr("backend.rpa.recording_runtime_agent.compact_recording_snapshot", fake_compact_recording_snapshot)

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="打开和Claudecode最相关的项目",
        runtime_results={},
    )

    files = sorted(debug_dir.glob("*-snapshot-*.json"))
    attempt_files = sorted(debug_dir.glob("*-attempt-*.json"))
    code_files = sorted(debug_dir.glob("*-code-*.py"))
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    repair_payload = next(item for item in payloads if item["stage"] == "repair")
    attempt_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in attempt_files]
    failed_attempt = next(item for item in attempt_payloads if item["stage"] == "initial_attempt")

    assert result.success is True
    assert len(files) == 2
    assert len(attempt_files) == 2
    assert len(code_files) == 2
    assert [path.name for path in files] == [
        "001-initial-snapshot-打开和Claudecode最相关的项目.json",
        "003-repair-snapshot-打开和Claudecode最相关的项目.json",
    ]
    assert [path.name for path in attempt_files] == [
        "002-initial_attempt-attempt-Broken_search_strategy.json",
        "004-repair_attempt-attempt-Recovered.json",
    ]
    assert [path.name for path in code_files] == [
        "002-initial_attempt-code-Broken_search_strategy.py",
        "004-repair_attempt-code-Recovered.py",
    ]
    assert calls[1]["repair"]["snapshot_after_failure"]["url"] == "https://github.com/search"
    assert repair_payload["compact_snapshot"]["url"] == "https://github.com/search"
    assert repair_payload["error"].startswith("Locator.click")
    assert repair_payload["failure_analysis"]["type"] == "selector_timeout"
    assert failed_attempt["plan"]["description"] == "Broken search strategy"
    assert failed_attempt["generated_code"].startswith("async def run")
    assert failed_attempt["execution_result"]["success"] is False
    assert failed_attempt["failure_analysis"]["type"] == "selector_timeout"
    for file in files + attempt_files + code_files:
        file.unlink()


def test_classify_recording_failure_returns_unknown_without_hint_for_unseen_errors():
    analysis = _classify_recording_failure("some new browser error shape")

    assert analysis == {"type": "unknown"}


def test_classify_recording_failure_identifies_selector_timeout_without_confidence():
    analysis = _classify_recording_failure(
        'Page.wait_for_selector: Timeout 15000ms exceeded waiting for locator("a.Link--primary[href*=issues]")'
    )

    assert analysis["type"] == "selector_timeout"
    assert "hint" in analysis
    assert "confidence" not in analysis


def test_classify_recording_failure_identifies_actionability_failure_before_selector_timeout():
    analysis = _classify_recording_failure(
        "Locator.fill: Timeout 60000ms exceeded\n"
        "Call log:\n"
        "  - waiting for locator(\"#kw\")\n"
        "    - locator resolved to <input id=\"kw\" />\n"
        "  - attempting fill action\n"
        "    - element is not visible\n"
        "    - waiting for element to be visible, enabled and editable"
    )

    assert analysis["type"] == "element_not_visible_or_not_editable"
    assert "hint" in analysis
    assert "confidence" not in analysis


@pytest.mark.asyncio
async def test_recording_runtime_agent_repair_payload_includes_page_after_failure():
    calls = []

    async def planner(payload):
        calls.append(payload)
        if "repair" not in payload:
            return {
                "description": "Open search engine and fill hidden input",
                "action_type": "run_python",
                "expected_effect": "mixed",
                "code": (
                    "async def run(page, results):\n"
                    "    await page.goto('https://www.baidu.com')\n"
                    "    raise RuntimeError('Locator.fill: Timeout 60000ms exceeded; element is not visible')"
                ),
            }
        return {
            "description": "Search by visible input",
            "action_type": "run_python",
            "expected_effect": "navigate",
            "output_key": "search_result",
            "code": (
                "async def run(page, results):\n"
                "    await page.goto('https://www.baidu.com/s?wd=pi-hole%2Fpi-hole')\n"
                "    return {'url': page.url}"
            ),
        }

    page = _FakePage()
    page.url = "https://github.com/pi-hole/pi-hole"
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction='填写"pi-hole/pi-hole"到搜索框点击搜索',
        runtime_results={},
    )

    repair = calls[1]["repair"]
    assert result.success is True
    assert calls[1]["page"]["url"] == "https://github.com/pi-hole/pi-hole"
    assert repair["page_after_failure"]["url"] == "https://www.baidu.com"
    assert repair["snapshot_after_failure"]["url"] == "https://www.baidu.com"
    assert repair["failure_analysis"]["type"] == "element_not_visible_or_not_editable"


@pytest.mark.asyncio
async def test_recording_runtime_agent_auto_navigates_when_open_command_returns_target_url():
    async def planner(_payload):
        return {
            "description": "Find highest-star repo",
            "action_type": "run_python",
            "expected_effect": "navigate",
            "output_key": "selected_project",
            "code": (
                "async def run(page, results):\n"
                "    return {'name': 'ruvnet/RuView', 'url': 'https://github.com/ruvnet/RuView', 'stars': 47505}"
            ),
        }

    page = _FakePage()
    page.url = "https://github.com/trending"
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction="打开star数最多的项目",
        runtime_results={},
    )

    assert result.success is True
    assert page.url == "https://github.com/ruvnet/RuView"
    assert result.trace.after_page.url == "https://github.com/ruvnet/RuView"
    assert result.trace.ai_execution.output["url"] == "https://github.com/ruvnet/RuView"


@pytest.mark.asyncio
async def test_recording_runtime_agent_keeps_page_when_extract_command_returns_url():
    async def planner(_payload):
        return {
            "description": "Find highest-star repo",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "selected_project",
            "code": (
                "async def run(page, results):\n"
                "    return {'name': 'ruvnet/RuView', 'url': 'https://github.com/ruvnet/RuView', 'stars': 47505}"
            ),
        }

    page = _FakePage()
    page.url = "https://github.com/trending"
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction="找到star数最多的项目",
        runtime_results={},
    )

    assert result.success is True
    assert page.url == "https://github.com/trending"
    assert result.trace.after_page.url == "https://github.com/trending"
    assert result.output["url"] == "https://github.com/ruvnet/RuView"


@pytest.mark.asyncio
async def test_recording_runtime_agent_restores_page_after_extract_uses_machine_endpoint():
    async def planner(_payload):
        return {
            "description": "Extract latest issue title",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "latest_issue",
            "code": (
                "async def run(page, results):\n"
                "    await page.goto('https://api.github.com/repos/ruvnet/RuView/issues?per_page=1')\n"
                "    return {'title': 'Latest issue'}"
            ),
        }

    page = _FakePage()
    page.url = "https://github.com/ruvnet/RuView"
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction="find the latest issue title",
        runtime_results={},
    )

    assert result.success is True
    assert page.url == "https://github.com/ruvnet/RuView"
    assert result.trace.after_page.url == "https://github.com/ruvnet/RuView"
    assert result.output == {"title": "Latest issue"}


@pytest.mark.asyncio
async def test_recording_runtime_agent_restores_to_last_user_page_after_extract_api_fallback():
    async def planner(_payload):
        return {
            "description": "Extract latest issue title",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "latest_issue",
            "code": (
                "async def run(page, results):\n"
                "    await page.goto('https://github.com/ruvnet/RuView/issues?q=is%3Aissue')\n"
                "    await page.goto('https://api.github.com/repos/ruvnet/RuView/issues?per_page=1')\n"
                "    return {'title': 'Latest issue'}"
            ),
        }

    page = _FakePage()
    page.url = "https://github.com/ruvnet/RuView"
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction="find the latest issue title",
        runtime_results={},
    )

    assert result.success is True
    assert page.url == "https://github.com/ruvnet/RuView/issues?q=is%3Aissue"
    assert result.trace.after_page.url == "https://github.com/ruvnet/RuView/issues?q=is%3Aissue"
    assert result.trace.ai_execution.output == {"title": "Latest issue"}


@pytest.mark.asyncio
async def test_recording_runtime_agent_accepts_empty_extract_output_without_forcing_repair():
    async def planner(_payload):
        return {
            "description": "Extract latest issue title",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "latest_issue",
            "code": "async def run(page, results):\n    return {'latest_issue_title': None, 'latest_issue_link': None}",
        }

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="find the latest issue title",
        runtime_results={},
    )

    assert result.success is True
    assert result.trace.ai_execution.repair_attempted is False
    assert result.output == {"latest_issue_title": None, "latest_issue_link": None}
    assert result.diagnostics == []


@pytest.mark.asyncio
async def test_recording_runtime_agent_accepts_empty_extract_when_plan_explicitly_allows_empty():
    async def planner(_payload):
        return {
            "description": "Collect optional notifications",
            "action_type": "run_python",
            "expected_effect": "extract",
            "allow_empty_output": True,
            "output_key": "notifications",
            "code": "async def run(page, results):\n    return {'notifications': []}",
        }

    result = await RecordingRuntimeAgent(planner=planner).run(
        page=_FakePage(),
        instruction="collect notifications if any, empty is acceptable",
        runtime_results={},
    )

    assert result.success is True
    assert result.output == {"notifications": []}


@pytest.mark.asyncio
async def test_recording_runtime_agent_records_download_signal_from_ai_code():
    async def planner(_payload):
        return {
            "description": "Download report",
            "action_type": "run_python",
            "expected_effect": "click",
            "output_key": "download_report",
            "code": (
                "async def run(page, results):\n"
                "    await page.trigger_download('report.xlsx')\n"
                "    return {'action_performed': True}"
            ),
        }

    page = _FakePage()
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction="download the report",
        runtime_results={},
    )

    assert result.success is True
    assert result.trace.signals["download"]["filename"] == "report.xlsx"
    assert result.trace.signals["download"]["count"] == 1


@pytest.mark.asyncio
async def test_recording_runtime_agent_waits_briefly_for_click_triggered_download():
    async def planner(_payload):
        return {
            "description": "Click table row column action",
            "action_type": "run_python",
            "expected_effect": "none",
            "output_key": "table_row_action",
            "code": (
                "async def run(page, results):\n"
                "    page.trigger_download_later('delayed-report.xlsx')\n"
                "    await page.locator('tbody tr').nth(0).click()\n"
                "    return {'action_performed': True}"
            ),
        }

    page = _FakePage()
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction="click the first file name in the export table",
        runtime_results={},
    )

    assert result.success is True
    assert result.trace.signals["download"]["filename"] == "delayed-report.xlsx"
    assert result.trace.output_key == "table_row_action"


@pytest.mark.asyncio
async def test_recording_runtime_agent_rejects_open_command_without_navigation_evidence_or_url():
    async def planner(_payload):
        return {
            "description": "Broken open",
            "action_type": "run_python",
            "expected_effect": "navigate",
            "code": "async def run(page, results):\n    return {'ok': True}",
        }

    page = _FakePage()
    page.url = "https://github.com/trending"
    result = await RecordingRuntimeAgent(planner=planner).run(
        page=page,
        instruction="打开star数最多的项目",
        runtime_results={},
    )

    assert result.success is False
    assert page.url == "https://github.com/trending"
    assert result.trace is None
    assert "navigation" in result.diagnostics[-1].message.lower()


def test_parse_json_object_accepts_fenced_json():
    payload = {
        "description": "Run",
        "action_type": "run_python",
        "code": "async def run(page, results):\n    return {'ok': True}",
    }

    parsed = _parse_json_object("prefix\n```json\n" + json.dumps(payload) + "\n```")

    assert parsed["description"] == "Run"
    assert "async def run(page, results)" in parsed["code"]


def test_parse_json_object_accepts_fenced_json_with_trailing_prose():
    payload = {
        "description": "Run",
        "action_type": "run_python",
        "code": "async def run(page, results):\n    return {'ok': True}",
    }

    parsed = _parse_json_object("```json\n" + json.dumps(payload) + "\n```\nThis is the plan.")

    assert parsed["description"] == "Run"
    assert "async def run(page, results)" in parsed["code"]


def test_parse_json_object_accepts_first_valid_object_before_trailing_text():
    payload = {
        "description": "Run",
        "action_type": "run_python",
        "code": "async def run(page, results):\n    return {'ok': True}",
    }

    parsed = _parse_json_object(json.dumps(payload) + "\nI will now execute this step with {notes}.")

    assert parsed["description"] == "Run"
    assert "async def run(page, results)" in parsed["code"]


def test_parse_json_object_skips_prose_example_before_valid_plan():
    payload = {
        "description": "Run actual plan",
        "action_type": "run_python",
        "code": "async def run(page, results):\n    return {'ok': True}",
    }

    parsed = _parse_json_object('Example: {"foo": "bar"}\nPlan:\n' + json.dumps(payload))

    assert parsed["description"] == "Run actual plan"
    assert "async def run(page, results)" in parsed["code"]


def test_parse_json_object_rejects_invalid_primary_plan_before_later_example():
    invalid_primary = {
        "description": "Invalid primary plan",
        "action_type": "run_python",
        "code": "print('missing async runner')",
    }
    later_example = {
        "description": "Example only",
        "action_type": "run_python",
        "code": "async def run(page, results):\n    return {'example': True}",
    }

    with pytest.raises(ValueError, match="async def run"):
        _parse_json_object(json.dumps(invalid_primary) + "\nExample fallback:\n" + json.dumps(later_example))


def test_snapshot_plan_fields_accepts_mapping_values_and_preserves_list_fields():
    list_fields = [{"label": "Owner", "value": "Ada", "visible": False}]

    assert _snapshot_plan_fields({"fields": {"Project": "Apollo"}}) == [
        {"label": "Project", "value": "Apollo"}
    ]
    assert _snapshot_plan_fields({"fields": list_fields}) == list_fields


def test_snapshot_plan_fields_flattens_nested_label_value_objects():
    assert _snapshot_plan_fields(
        {
            "fields": {
                "contract_number": {
                    "label": "合同编号",
                    "value": "CT-001",
                }
            }
        }
    ) == [{"label": "contract_number", "value": "CT-001", "observed_label": "合同编号"}]


def test_extract_snapshot_enrichment_backfills_observed_label_from_detail_value():
    result = {
        "signals": {
            "extract_snapshot": {
                "fields": [
                    {
                        "label": "compliance_summary",
                        "value": "Must keep audit logs.",
                        "replay_required": True,
                    }
                ]
            }
        }
    }
    snapshot = {
        "detail_views": [
            {
                "fields": [
                    {
                        "label": "Compliance clause",
                        "value": "Must keep audit logs.",
                    }
                ]
            }
        ]
    }

    enriched = recording_runtime_agent._enrich_extract_snapshot_result_with_replay_evidence(result, snapshot)

    field = enriched["signals"]["extract_snapshot"]["fields"][0]
    assert field["observed_label"] == "Compliance clause"


def test_extract_snapshot_enrichment_overrides_unobserved_label_from_detail_value():
    result = {
        "signals": {
            "extract_snapshot": {
                "fields": [
                    {
                        "label": "compliance_summary",
                        "value": "Must keep audit logs.",
                        "observed_label": "Compliance summary",
                        "replay_required": True,
                    }
                ]
            }
        }
    }
    snapshot = {
        "detail_views": [
            {
                "fields": [
                    {
                        "label": "Compliance clause",
                        "value": "Must keep audit logs.",
                    }
                ]
            }
        ]
    }

    enriched = recording_runtime_agent._enrich_extract_snapshot_result_with_replay_evidence(result, snapshot)

    field = enriched["signals"]["extract_snapshot"]["fields"][0]
    assert field["observed_label"] == "Compliance clause"


def test_extract_snapshot_enrichment_resolves_label_value_mistake_from_detail_view():
    result = {
        "output": {"contract_number": "Contract number"},
        "signals": {
            "extract_snapshot": {
                "fields": [
                    {
                        "label": "contract_number",
                        "value": "Contract number",
                        "replay_required": True,
                    }
                ]
            }
        },
    }
    snapshot = {
        "detail_views": [
            {
                "fields": [
                    {
                        "label": "Contract number",
                        "value": "CT-001",
                    }
                ]
            }
        ]
    }

    enriched = recording_runtime_agent._enrich_extract_snapshot_result_with_replay_evidence(result, snapshot)

    field = enriched["signals"]["extract_snapshot"]["fields"][0]
    assert field["observed_label"] == "Contract number"
    assert field["value"] == "CT-001"
    assert enriched["output"]["contract_number"] == "CT-001"


def test_parse_json_object_rejects_run_python_without_runner():
    payload = {"description": "Bad", "action_type": "run_python", "code": "print('bad')"}

    with pytest.raises(ValueError):
        _parse_json_object(json.dumps(payload))

