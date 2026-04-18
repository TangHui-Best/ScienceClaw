from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RpaMcpSource(BaseModel):
    type: str = "rpa_skill"
    session_id: str
    skill_name: str = ""


class RpaMcpSanitizeReport(BaseModel):
    removed_steps: list[int] = Field(default_factory=list)
    removed_params: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RpaMcpToolDefinition(BaseModel):
    id: str
    user_id: str
    name: str
    tool_name: str
    description: str = ""
    enabled: bool = True
    source: RpaMcpSource
    allowed_domains: list[str] = Field(default_factory=list)
    post_auth_start_url: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    sanitize_report: RpaMcpSanitizeReport = Field(default_factory=RpaMcpSanitizeReport)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
