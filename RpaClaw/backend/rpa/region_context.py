from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class RPARegionRect(BaseModel):
    x: float
    y: float
    width: float
    height: float


class RPARegionViewport(BaseModel):
    width: float
    height: float


class RPARegionAnalyzeRequest(BaseModel):
    tab_id: str
    rect: RPARegionRect
    viewport: RPARegionViewport


class RPARegionEvidence(BaseModel):
    url: str = ""
    title: str = ""
    frame_path: List[str] = Field(default_factory=list)
    rect: Dict[str, float] = Field(default_factory=dict)
    dominant_container: Dict[str, Any] = Field(default_factory=dict)
    intersecting_elements: List[Dict[str, Any]] = Field(default_factory=list)
    locator_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    local_text: List[str] = Field(default_factory=list)
    inferred_kind: str = "unknown"
    table_summary: Optional[Dict[str, Any]] = None
    list_summary: Optional[Dict[str, Any]] = None
    action_summary: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)


class RPARegionContext(BaseModel):
    region_id: str = Field(default_factory=lambda: f"region-{uuid4().hex}")
    session_id: str
    tab_id: str
    page_url: str = ""
    page_title: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    evidence: RPARegionEvidence

    def preview(self) -> Dict[str, Any]:
        rect = self.evidence.rect or {}
        width = int(float(rect.get("width", 0) or 0))
        height = int(float(rect.get("height", 0) or 0))
        element_count = len(self.evidence.intersecting_elements)
        return {
            "region_id": self.region_id,
            "tab_id": self.tab_id,
            "summary": f"区域 {width}x{height}，包含 {element_count} 个元素",
            "inferred_kind": self.evidence.inferred_kind,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "warnings": list(self.evidence.warnings),
        }


class RPARegionAnalyzeResponse(BaseModel):
    region_id: str
    summary: str
    inferred_kind: str = "unknown"
    evidence: RPARegionEvidence
