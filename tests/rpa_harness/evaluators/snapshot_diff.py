from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from backend.rpa.snapshot_compression import compact_recording_snapshot
from tests.rpa_harness.evaluators.dom_morphology import DomMorphologyCase


@dataclass(frozen=True)
class SnapshotFact:
    key: str
    value: str
    layer: str


@dataclass(frozen=True)
class SnapshotDiffResult:
    case_id: str
    title: str
    task_shape: str
    passed: bool
    attribution_layer: str
    missing_facts: list[SnapshotFact] = field(default_factory=list)
    checked_fact_keys: list[str] = field(default_factory=list)
    raw_fact_count: int = 0
    compact_fact_count: int = 0


@dataclass(frozen=True)
class SnapshotDiffSummary:
    case_count: int
    passed_count: int
    failed_count: int
    results: list[SnapshotDiffResult]

    @property
    def passed(self) -> bool:
        return self.failed_count == 0


class SnapshotFactExtractor:
    def extract(self, payload: dict[str, Any], task_shape: str, layer: str) -> list[SnapshotFact]:
        facts: list[SnapshotFact] = []
        facts.extend(_extract_detail_facts(payload, layer))
        facts.extend(_extract_table_facts(payload, layer))
        facts.extend(_extract_candidate_facts(payload, layer))
        facts.extend(_extract_form_facts(payload, layer))
        facts.extend(_extract_iframe_facts(payload, layer))
        facts.extend(_extract_text_facts(payload, task_shape, layer))
        return _dedupe_facts(facts)


class SnapshotDiffEvaluator:
    def __init__(self, cases: Iterable[DomMorphologyCase]) -> None:
        self.cases = list(cases)
        self.extractor = SnapshotFactExtractor()

    @classmethod
    def from_directory(cls, case_root: Path) -> "SnapshotDiffEvaluator":
        return cls(
            DomMorphologyCase.from_path(path)
            for path in sorted(case_root.glob("*/case.json"))
        )

    def evaluate(self) -> list[SnapshotDiffResult]:
        return [self._evaluate_case(case) for case in self.cases]

    def summarize(self) -> SnapshotDiffSummary:
        results = self.evaluate()
        passed_count = sum(1 for result in results if result.passed)
        return SnapshotDiffSummary(
            case_count=len(results),
            passed_count=passed_count,
            failed_count=len(results) - passed_count,
            results=results,
        )

    def _evaluate_case(self, case: DomMorphologyCase) -> SnapshotDiffResult:
        raw_facts = self.extractor.extract(case.raw_snapshot, case.task_shape, "raw")
        raw_text = _flatten_text(case.raw_snapshot)
        raw_missing = [
            SnapshotFact(
                key=f"expected.raw.{fact}",
                value=fact,
                layer="raw",
            )
            for fact in case.expected_raw_facts
            if fact not in raw_text
        ]

        compact_snapshot = compact_recording_snapshot(
            case.raw_snapshot,
            case.instruction,
            char_budget=case.char_budget,
        )
        compact_facts = self.extractor.extract(compact_snapshot, case.task_shape, "compact")
        compact_text = _flatten_text(compact_snapshot)

        checked_keys = _checked_keys(case, raw_facts)
        if raw_missing:
            return SnapshotDiffResult(
                case_id=case.case_id,
                title=case.title,
                task_shape=case.task_shape,
                passed=False,
                attribution_layer="raw_missing",
                missing_facts=raw_missing,
                checked_fact_keys=checked_keys,
                raw_fact_count=len(raw_facts),
                compact_fact_count=len(compact_facts),
            )

        compact_missing = []
        for expected in case.expected_compact_facts:
            if expected not in compact_text:
                compact_missing.append(
                    _missing_compact_fact(expected, raw_facts, "expected.compact")
                )
        for locator in case.expected_locator_preservation:
            if locator not in compact_text:
                compact_missing.append(
                    _missing_compact_fact(locator, raw_facts, "expected.locator")
                )

        if compact_missing:
            return SnapshotDiffResult(
                case_id=case.case_id,
                title=case.title,
                task_shape=case.task_shape,
                passed=False,
                attribution_layer="compact_loss",
                missing_facts=compact_missing,
                checked_fact_keys=checked_keys,
                raw_fact_count=len(raw_facts),
                compact_fact_count=len(compact_facts),
            )

        return SnapshotDiffResult(
            case_id=case.case_id,
            title=case.title,
            task_shape=case.task_shape,
            passed=True,
            attribution_layer="passed",
            checked_fact_keys=checked_keys,
            raw_fact_count=len(raw_facts),
            compact_fact_count=len(compact_facts),
        )


def _checked_keys(case: DomMorphologyCase, raw_facts: list[SnapshotFact]) -> list[str]:
    keys: list[str] = []
    for expected in [*case.expected_compact_facts, *case.expected_locator_preservation]:
        matching = _find_fact_containing(raw_facts, expected)
        keys.append(matching.key if matching else f"expected.compact.{expected}")
    return sorted(set(keys))


def _missing_compact_fact(
    expected: str,
    raw_facts: list[SnapshotFact],
    fallback_prefix: str,
) -> SnapshotFact:
    matching = _find_fact_containing(raw_facts, expected)
    if matching:
        return SnapshotFact(key=matching.key, value=expected, layer="compact")
    return SnapshotFact(key=f"{fallback_prefix}.{expected}", value=expected, layer="compact")


def _find_fact_containing(facts: list[SnapshotFact], expected: str) -> SnapshotFact | None:
    for fact in facts:
        if expected in fact.value or expected in fact.key:
            return fact
    return None


def _extract_detail_facts(payload: dict[str, Any], layer: str) -> list[SnapshotFact]:
    facts: list[SnapshotFact] = []
    for pair in _iter_pair_payloads(payload):
        label = _clean_label(pair.get("label"))
        value = _clean_text(pair.get("value"))
        if not label:
            continue
        facts.append(SnapshotFact(f"detail.field.{label}", label, layer))
        if value:
            facts.append(SnapshotFact(f"detail.value.{label}", value, layer))
        for locator_key in ("label_locator", "value_locator"):
            locator_text = _flatten_text(pair.get(locator_key) or {})
            if locator_text:
                facts.append(SnapshotFact(f"detail.locator.{label}", locator_text, layer))

    content_nodes = list(payload.get("content_nodes") or [])
    labels = [
        node for node in content_nodes
        if _normalize(node.get("semantic_kind")) == "label"
    ]
    values = [
        node for node in content_nodes
        if _normalize(node.get("semantic_kind")) == "field_value"
    ]
    for label_node in labels:
        label = _clean_label(label_node.get("text"))
        if not label:
            continue
        facts.append(SnapshotFact(f"detail.field.{label}", label, layer))
        value_node = _nearest_value(label_node, values)
        if value_node:
            value = _clean_text(value_node.get("text"))
            if value:
                facts.append(SnapshotFact(f"detail.value.{label}", value, layer))
            locator_text = _flatten_text(value_node.get("locator") or {})
            if locator_text:
                facts.append(SnapshotFact(f"detail.locator.{label}", locator_text, layer))
    return facts


def _extract_table_facts(payload: dict[str, Any], layer: str) -> list[SnapshotFact]:
    facts: list[SnapshotFact] = []
    for table in _iter_dicts_named(payload, "table_views"):
        for column in table.get("columns") or []:
            header = _clean_text(column.get("header") or column.get("column_header"))
            if header:
                facts.append(SnapshotFact(f"table.column.{header}", header, layer))
        for row in table.get("rows") or []:
            row_parts: list[str] = []
            for cell in row.get("cells") or []:
                text = _clean_text(cell.get("text"))
                if text:
                    row_parts.append(text)
                for action in cell.get("actions") or cell.get("row_local_actions") or []:
                    label = _clean_text(action.get("label"))
                    locator = _flatten_text(action.get("locator") or {})
                    if label:
                        facts.append(SnapshotFact(f"table.action.{label}", locator or label, layer))
            if row_parts:
                row_text = " / ".join(row_parts)
                facts.append(SnapshotFact(f"table.row.{row_parts[0]}", row_text, layer))

    for region in _iter_regions(payload):
        if region.get("kind") != "table":
            continue
        evidence = region.get("evidence") or {}
        for header in evidence.get("headers") or []:
            header_text = _clean_text(header)
            if header_text:
                facts.append(SnapshotFact(f"table.column.{header_text}", header_text, layer))
        for row in evidence.get("sample_rows") or []:
            row_parts = [_clean_text(item) for item in row if _clean_text(item)]
            if row_parts:
                facts.append(SnapshotFact(f"table.row.{row_parts[0]}", " / ".join(row_parts), layer))
        for hint in region.get("locator_hints") or []:
            facts.append(SnapshotFact("table.locator.table", _flatten_text(hint), layer))

    headers = [
        _clean_text(node.get("text"))
        for node in payload.get("content_nodes") or []
        if _normalize(node.get("semantic_kind")) == "header_cell"
    ]
    for header in headers:
        if header:
            facts.append(SnapshotFact(f"table.column.{header}", header, layer))
    return facts


def _extract_candidate_facts(payload: dict[str, Any], layer: str) -> list[SnapshotFact]:
    facts: list[SnapshotFact] = []
    for item in _iter_candidate_items(payload):
        title = _clean_text(item.get("primary_text") or item.get("text") or item.get("name"))
        if not title:
            continue
        facts.append(SnapshotFact(f"candidate.title.{title}", title, layer))
        secondary = _clean_text(item.get("secondary_text"))
        if secondary:
            facts.append(SnapshotFact(f"candidate.metadata.{title}", secondary, layer))
        locator = _flatten_text(item.get("locator") or {})
        if locator:
            facts.append(SnapshotFact(f"candidate.locator.{title}", locator, layer))

    nodes = sorted(
        list(payload.get("content_nodes") or []),
        key=lambda node: (_node_y(node), _node_x(node), str(node.get("node_id") or "")),
    )
    anchors = [
        node for node in nodes
        if _normalize(node.get("semantic_kind")) == "item"
        and _clean_text(node.get("text") or node.get("name"))
    ]
    for index, anchor in enumerate(anchors):
        title = _clean_text(anchor.get("text") or anchor.get("name"))
        facts.append(SnapshotFact(f"candidate.title.{title}", title, layer))
        locator = _flatten_text(anchor.get("locator") or {})
        if locator:
            facts.append(SnapshotFact(f"candidate.locator.{title}", locator, layer))
        next_y = _node_y(anchors[index + 1]) if index + 1 < len(anchors) else None
        metadata = [
            _clean_text(node.get("text") or node.get("name"))
            for node in nodes
            if node is not anchor
            and _node_y(node) >= _node_y(anchor)
            and (next_y is None or _node_y(node) < next_y)
            and _normalize(node.get("semantic_kind")) != "item"
            and _clean_text(node.get("text") or node.get("name"))
        ]
        if metadata:
            facts.append(SnapshotFact(f"candidate.metadata.{title}", " ".join(metadata), layer))
    return facts


def _extract_form_facts(payload: dict[str, Any], layer: str) -> list[SnapshotFact]:
    facts: list[SnapshotFact] = []
    for view in _iter_dicts_named(payload, "form_views"):
        for field in view.get("fields") or []:
            label = _clean_label(field.get("label"))
            if not label:
                continue
            facts.append(SnapshotFact(f"form.field.{label}", label, layer))
            control = field.get("control") or {}
            placeholder = _clean_text(control.get("placeholder"))
            if placeholder:
                facts.append(SnapshotFact(f"form.placeholder.{label}", placeholder, layer))
            locator = _flatten_text(control.get("locator") or {})
            if locator:
                facts.append(SnapshotFact(f"form.locator.{label}", locator, layer))

    labels = [
        node for node in payload.get("content_nodes") or []
        if _normalize(node.get("semantic_kind")) == "label"
    ]
    controls = list(payload.get("actionable_nodes") or [])
    for label_node in labels:
        label = _clean_label(label_node.get("text"))
        if not label:
            continue
        facts.append(SnapshotFact(f"form.field.{label}", label, layer))
        control = _nearest_control(label_node, controls)
        if not control:
            continue
        placeholder = _clean_text(control.get("placeholder"))
        if placeholder:
            facts.append(SnapshotFact(f"form.placeholder.{label}", placeholder, layer))
        locator = _flatten_text(control.get("locator") or {})
        if locator:
            facts.append(SnapshotFact(f"form.locator.{label}", locator, layer))
    return facts


def _extract_iframe_facts(payload: dict[str, Any], layer: str) -> list[SnapshotFact]:
    facts: list[SnapshotFact] = []
    for frame_path in _iter_frame_paths(payload):
        path_text = " > ".join(str(item) for item in frame_path if str(item))
        if path_text:
            facts.append(SnapshotFact(f"iframe.frame_path.{path_text}", path_text, layer))
    return facts


def _extract_text_facts(payload: dict[str, Any], task_shape: str, layer: str) -> list[SnapshotFact]:
    facts: list[SnapshotFact] = []
    for text in _iter_text_values(payload):
        clean = _clean_text(text)
        if clean:
            facts.append(SnapshotFact(f"{task_shape}.text.{clean[:64]}", clean, layer))
    return facts


def _iter_pair_payloads(payload: Any) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("label"), str) and "value" in payload:
            pairs.append(payload)
        for value in payload.values():
            pairs.extend(_iter_pair_payloads(value))
    elif isinstance(payload, list):
        for item in payload:
            pairs.extend(_iter_pair_payloads(item))
    return pairs


def _iter_dicts_named(payload: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items = payload.get(key)
    return [item for item in items or [] if isinstance(item, dict)]


def _iter_regions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for key in ("expanded_regions", "sampled_regions", "region_catalogue"):
        regions.extend(item for item in payload.get(key) or [] if isinstance(item, dict))
    return regions


def _iter_candidate_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for region in _iter_regions(payload):
        if region.get("kind") != "record_list":
            continue
        evidence = region.get("evidence") or {}
        items.extend(item for item in evidence.get("items") or [] if isinstance(item, dict))
    return items


def _iter_frame_paths(payload: Any) -> list[list[Any]]:
    paths: list[list[Any]] = []
    if isinstance(payload, dict):
        frame_path = payload.get("frame_path")
        if isinstance(frame_path, list):
            paths.append(frame_path)
        for value in payload.values():
            paths.extend(_iter_frame_paths(value))
    elif isinstance(payload, list):
        for item in payload:
            paths.extend(_iter_frame_paths(item))
    return paths


def _iter_text_values(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key in ("text", "title", "summary", "value", "label", "primary_text", "secondary_text"):
            value = payload.get(key)
            if isinstance(value, str):
                values.append(value)
        for value in payload.values():
            values.extend(_iter_text_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_iter_text_values(item))
    return values


def _nearest_value(label_node: dict[str, Any], values: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        value for value in values
        if _node_y(value) >= _node_y(label_node) - 4
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda value: (
            abs(_node_y(value) - _node_y(label_node)),
            abs(_node_x(value) - _node_x(label_node)),
        ),
    )


def _nearest_control(label_node: dict[str, Any], controls: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        control for control in controls
        if abs(_node_y(control) - _node_y(label_node)) <= 40
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda control: abs(_node_y(control) - _node_y(label_node)))


def _dedupe_facts(facts: list[SnapshotFact]) -> list[SnapshotFact]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[SnapshotFact] = []
    for fact in facts:
        marker = (fact.key, fact.value, fact.layer)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(fact)
    return deduped


def _flatten_text(payload: Any) -> str:
    if isinstance(payload, dict):
        return " ".join(_flatten_text(value) for value in payload.values())
    if isinstance(payload, list):
        return " ".join(_flatten_text(item) for item in payload)
    return str(payload)


def _node_y(node: dict[str, Any]) -> int:
    return int((node.get("bbox") or {}).get("y", 0) or 0)


def _node_x(node: dict[str, Any]) -> int:
    return int((node.get("bbox") or {}).get("x", 0) or 0)


def _clean_label(value: Any) -> str:
    text = _clean_text(value)
    while text.startswith("*"):
        text = _clean_text(text[1:])
    return text.rstrip(":").rstrip("：")


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def to_jsonable_summary(summary: SnapshotDiffSummary) -> dict[str, Any]:
    return json.loads(json.dumps(summary, default=lambda item: item.__dict__))
