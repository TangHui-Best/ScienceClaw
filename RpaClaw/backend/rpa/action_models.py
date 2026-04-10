from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LocatorValidation(BaseModel):
    status: str
    details: str = ""


class LocatorCandidate(BaseModel):
    kind: str
    score: int
    strict_match_count: int
    visible_match_count: int
    selected: bool = False
    locator: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    nth: Optional[int] = None
    selector: Optional[str] = None
    playwright_locator: Optional[str] = None
    actionability: Dict[str, Any] = Field(default_factory=dict)


class ActionSignal(BaseModel):
    navigation: Optional[Dict[str, Any]] = None
    popup: Optional[Dict[str, Any]] = None
    download: Optional[Dict[str, Any]] = None
    dialog: Optional[Dict[str, Any]] = None


class RecordedActionV2(BaseModel):
    id: str
    session_id: str
    tab_id: str
    page_alias: str
    frame_path: List[str] = Field(default_factory=list)
    action: str
    selector: str
    selector_source: str
    signals: ActionSignal = Field(default_factory=ActionSignal)
    value: Optional[str] = None
    modifiers: List[str] = Field(default_factory=list)
    position: Optional[Dict[str, Any]] = None
    timestamp: Optional[int] = None
    locator_candidates: List[LocatorCandidate] = Field(default_factory=list)
    element_snapshot: Dict[str, Any] = Field(default_factory=dict)
    validation: LocatorValidation
    status: str
