"""Pure-function query engine for FileRepository.

Supports the MongoDB query/update operators actually used in the codebase:
- Query: equality, $or, $gte, $lte, $ne, $in, $nin, $exists, $not
- Update: $set, $push, $setOnInsert
- Nested field access via dot notation (e.g. "events.0")
"""
from __future__ import annotations

import copy
from typing import Any


def _get_nested(doc: dict, key: str) -> tuple[bool, Any]:
    """Get a possibly-nested value. Returns (found, value)."""
    parts = key.split(".")
    current = doc
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return False, None
        else:
            return False, None
    return True, current


def _match_value(doc_val: Any, condition: Any) -> bool:
    """Match a single field value against a condition (scalar or operator dict)."""
    if isinstance(condition, dict) and condition:
        first_key = next(iter(condition))
        if first_key.startswith("$"):
            return _match_operators(doc_val, condition)
    return doc_val == condition


def _match_operators(doc_val: Any, ops: dict) -> bool:
    """Evaluate operator dict against a document value."""
    for op, val in ops.items():
        if op == "$gte":
            if doc_val is None or doc_val < val:
                return False
        elif op == "$lte":
            if doc_val is None or doc_val > val:
                return False
        elif op == "$gt":
            if doc_val is None or doc_val > val:
                return False
        elif op == "$lt":
            if doc_val is None or doc_val < val:
                return False
        elif op == "$ne":
            if doc_val == val:
                return False
        elif op == "$in":
            if doc_val not in val:
                return False
        elif op == "$nin":
            if doc_val in val:
                return False
        elif op == "$exists":
            exists = doc_val is not None
            if val and not exists:
                return False
            if not val and exists:
                return False
        elif op == "$not":
            if _match_value(doc_val, val):
                return False
        else:
            raise NotImplementedError(f"Query operator not supported: {op}")
    return True


def match_filter(doc: dict, filter: dict) -> bool:
    """Return True if doc matches the MongoDB-style filter."""
    for key, condition in filter.items():
        if key == "$or":
            if not any(match_filter(doc, sub) for sub in condition):
                return False
        elif key == "$and":
            if not all(match_filter(doc, sub) for sub in condition):
                return False
        else:
            found, doc_val = _get_nested(doc, key)
            if isinstance(condition, dict) and "$exists" in condition:
                exists = found
                if condition["$exists"] and not exists:
                    return False
                if not condition["$exists"] and exists:
                    return False
                remaining = {k: v for k, v in condition.items() if k != "$exists"}
                if remaining and not _match_operators(doc_val, remaining):
                    return False
            else:
                if not found:
                    if isinstance(condition, dict):
                        if not _match_operators(None, condition):
                            return False
                    elif condition is not None:
                        return False
                elif not _match_value(doc_val, condition):
                    return False
    return True


def apply_projection(doc: dict, projection: dict | None) -> dict:
    """Apply MongoDB-style projection. Only inclusion projections supported."""
    if not projection:
        return doc
    vals = [v for k, v in projection.items() if k != "_id"]
    if not vals:
        return doc
    if vals[0]:
        result = {}
        if "_id" in doc:
            result["_id"] = doc["_id"]
        for key, include in projection.items():
            if include and key in doc:
                result[key] = doc[key]
        return result
    else:
        result = dict(doc)
        for key, include in projection.items():
            if not include and key in result:
                del result[key]
        return result


def apply_update(doc: dict, update: dict, is_upsert_insert: bool = False) -> dict:
    """Apply MongoDB-style update operators to a document (mutates a copy).

    Supports: $set, $push, $setOnInsert, and whole-doc replacement.
    """
    doc = copy.deepcopy(doc)

    has_operators = any(k.startswith("$") for k in update)

    if not has_operators:
        _id = doc.get("_id")
        doc = copy.deepcopy(update)
        if _id is not None:
            doc["_id"] = _id
        return doc

    if "$set" in update:
        for key, val in update["$set"].items():
            doc[key] = val

    if "$push" in update:
        for key, val in update["$push"].items():
            if key not in doc:
                doc[key] = []
            if isinstance(doc[key], list):
                doc[key].append(val)

    if "$setOnInsert" in update and is_upsert_insert:
        for key, val in update["$setOnInsert"].items():
            if key not in doc:
                doc[key] = val

    return doc
