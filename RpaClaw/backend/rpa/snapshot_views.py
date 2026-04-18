from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List
from uuid import uuid4


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _limited(items: List[Dict[str, Any]], limit: int) -> tuple[List[Dict[str, Any]], bool]:
    safe_limit = max(int(limit), 0)
    return deepcopy(items[:safe_limit]), len(items) > safe_limit


@dataclass
class BaseSnapshot:
    url: str = ""
    title: str = ""
    snapshot_id: str = field(default_factory=lambda: f"snapshot_{uuid4().hex}")
    actionable_nodes: List[Dict[str, Any]] = field(default_factory=list)
    content_nodes: List[Dict[str, Any]] = field(default_factory=list)
    containers: List[Dict[str, Any]] = field(default_factory=list)
    frames: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def action_view(self, max_nodes: int = 120) -> Dict[str, Any]:
        nodes, truncated = _limited(self.actionable_nodes, max_nodes)
        return {
            "snapshot_id": self.snapshot_id,
            "url": self.url,
            "title": self.title,
            "nodes": nodes,
            "truncated": truncated,
            "total_nodes": len(self.actionable_nodes),
        }

    def extraction_view(
        self,
        max_collections: int = 8,
        max_items_per_collection: int = 25,
    ) -> Dict[str, Any]:
        collections: List[Dict[str, Any]] = []
        truncated = False

        for frame in self.frames:
            for collection in _as_list(frame.get("collections")):
                if len(collections) >= max_collections:
                    truncated = True
                    break

                collection_copy = deepcopy(collection)
                items = _as_list(collection_copy.get("items"))
                if items:
                    limited_items, items_truncated = _limited(items, max_items_per_collection)
                    collection_copy["items"] = limited_items
                    collection_copy["items_truncated"] = items_truncated
                    truncated = truncated or items_truncated
                collection_copy.setdefault("frame_path", frame.get("frame_path", []))
                collections.append(collection_copy)

            if len(collections) >= max_collections:
                remaining = sum(len(_as_list(frame.get("collections"))) for frame in self.frames)
                truncated = truncated or remaining > max_collections
                break

        return {
            "snapshot_id": self.snapshot_id,
            "url": self.url,
            "title": self.title,
            "collections": collections,
            "containers": deepcopy(self.containers),
            "truncated": truncated,
            "total_collections": sum(
                len(_as_list(frame.get("collections"))) for frame in self.frames
            ),
        }

    def semantic_view(self, max_content_nodes: int = 80) -> Dict[str, Any]:
        content_nodes, content_truncated = _limited(self.content_nodes, max_content_nodes)
        return {
            "snapshot_id": self.snapshot_id,
            "url": self.url,
            "title": self.title,
            "containers": deepcopy(self.containers),
            "content_nodes": content_nodes,
            "truncated": content_truncated,
            "total_content_nodes": len(self.content_nodes),
        }


def build_base_snapshot_from_legacy(snapshot: Dict[str, Any]) -> BaseSnapshot:
    safe_snapshot = snapshot if isinstance(snapshot, dict) else {}
    return BaseSnapshot(
        url=str(safe_snapshot.get("url") or ""),
        title=str(safe_snapshot.get("title") or ""),
        actionable_nodes=deepcopy(_as_list(safe_snapshot.get("actionable_nodes"))),
        content_nodes=deepcopy(_as_list(safe_snapshot.get("content_nodes"))),
        containers=deepcopy(_as_list(safe_snapshot.get("containers"))),
        frames=deepcopy(_as_list(safe_snapshot.get("frames"))),
        evidence=deepcopy(safe_snapshot),
    )
