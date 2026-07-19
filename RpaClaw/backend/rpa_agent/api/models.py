"""Strict, non-legacy request DTOs for the RPA Agent creation API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from ..contracts.models import BusinessVariableRef


Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._-]*$")
]
OpaqueHostRef = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
OpaqueModelRef = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
SessionId = Annotated[
    str, Field(pattern=r"^rca_[a-z0-9]{24}$", min_length=28, max_length=28)
]


def _parse_api_datetime(value: object) -> object:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


class ApiModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
    )


class StartSessionRequest(ApiModel):
    browser_session_ref: OpaqueHostRef


class BrowserRuntimeScope(ApiModel):
    page_runtime_ref: Identifier
    frame_runtime_ref: Identifier


class StartSessionResponse(ApiModel):
    session_id: SessionId
    state: Literal["recording"]
    main_scope: BrowserRuntimeScope


class ManualReservationRequest(ApiModel):
    candidate_id: Identifier
    page_runtime_ref: Identifier
    frame_runtime_ref: Identifier


class ManualEventRequest(ApiModel):
    reservation_token: Annotated[str, Field(min_length=32, max_length=256)]
    kind: Annotated[
        str,
        Field(pattern=r"^(focus|beforeinput|input|change|blur|click|compositionstart|compositionend)$"),
    ]
    interaction_kind: Annotated[str, Field(pattern=r"^(click|fill|set_checked)$")]
    page_runtime_ref: Identifier
    frame_runtime_ref: Identifier
    target_key: Annotated[str, Field(min_length=1, max_length=512)]
    target_name: Annotated[str, Field(min_length=1, max_length=512)]
    target_locators: Annotated[
        list[dict[str, JsonValue]], Field(min_length=1, max_length=32)
    ]
    observed_at: Annotated[datetime, BeforeValidator(_parse_api_datetime)]
    target_path: list[dict[str, JsonValue]] = Field(
        default_factory=list,
        max_length=32,
    )
    binding_hints: list[dict[str, JsonValue]] = Field(
        default_factory=list,
        max_length=64,
    )
    value: str | None = None
    checked: bool | None = None
    finish: bool = False

    @field_validator("observed_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("manual_event.observed_at_naive")
        return value


class ManualInputRequest(ApiModel):
    input_id: Identifier
    kind: Literal["click", "text", "paste"]
    x: Annotated[float, Field(ge=0, le=100_000)] | None = None
    y: Annotated[float, Field(ge=0, le=100_000)] | None = None
    text: Annotated[str, Field(min_length=1, max_length=65_536)] | None = None

    @model_validator(mode="after")
    def require_only_kind_fields(self) -> "ManualInputRequest":
        if self.kind == "click":
            if self.x is None or self.y is None:
                raise ValueError("manual_input.coordinates_required")
            if self.text is not None:
                raise ValueError("manual_input.text_forbidden")
        else:
            if self.text is None:
                raise ValueError("manual_input.text_required")
            if self.x is not None or self.y is not None:
                raise ValueError("manual_input.coordinates_forbidden")
        return self


class AgentInstructionRequest(ApiModel):
    instruction: Annotated[str, Field(min_length=1, max_length=20_000)]
    model_id: OpaqueModelRef | None = None
    business_terms: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=256)]],
        Field(max_length=64),
    ]
    required_variable_refs: Annotated[
        list[BusinessVariableRef], Field(max_length=128)
    ]
    allowed_inputs: Annotated[
        dict[Identifier, Annotated[str, Field(min_length=1, max_length=1000)]],
        Field(max_length=128),
    ]
    allowed_secret_names: Annotated[list[Identifier], Field(max_length=128)]
    allowed_data_assets: Annotated[
        dict[Identifier, Annotated[str, Field(min_length=1, max_length=1000)]],
        Field(max_length=128),
    ]
    page_aliases: Annotated[
        dict[Identifier, Annotated[str, Field(min_length=1, max_length=1000)]],
        Field(max_length=64),
    ]

    @field_validator("required_variable_refs")
    @classmethod
    def reject_numeric_variable_path_segments(cls, value: list[str]) -> list[str]:
        if any(part.isdigit() for ref in value for part in ref.split(".")):
            raise ValueError("api.required_variable_ref_numeric_segment")
        return value


class TestRunRequest(ApiModel):
    inputs: Annotated[dict[Identifier, JsonValue], Field(max_length=256)]
    secrets: Annotated[
        dict[Identifier, Annotated[str, Field(max_length=65_536)]],
        Field(max_length=256),
    ]
    data_assets: Annotated[
        dict[Identifier, Annotated[str, Field(min_length=1, max_length=512)]],
        Field(max_length=256),
    ]


def safe_json(value: Any) -> JsonValue:
    """Narrow helper used by response construction after an injected boundary."""

    from pydantic import TypeAdapter

    return TypeAdapter(JsonValue).validate_python(value)


__all__ = [
    "AgentInstructionRequest",
    "ApiModel",
    "BrowserRuntimeScope",
    "ManualEventRequest",
    "ManualInputRequest",
    "ManualReservationRequest",
    "OpaqueHostRef",
    "SessionId",
    "StartSessionRequest",
    "StartSessionResponse",
    "TestRunRequest",
    "safe_json",
]
