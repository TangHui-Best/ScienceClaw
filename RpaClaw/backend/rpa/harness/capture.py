from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .models import CaptureScope


class HarnessCaptureSessionState(BaseModel):
    capture_id: str = Field(default_factory=lambda: f"hcap-{uuid4().hex}")
    session_id: str
    capture_scope: CaptureScope
    selected_step_indexes: list[int] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.now)
    status: Literal["active", "stopped"] = "active"

    def mark_step_selected(self, step_index: int) -> None:
        if self.capture_scope != "selected_steps":
            return
        if step_index not in self.selected_step_indexes:
            self.selected_step_indexes.append(step_index)
            self.selected_step_indexes.sort()

