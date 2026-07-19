"""公开的 RPA Agent v0.1 契约。"""

from .models import (
    AcceptedSettlement,
    ActionHint,
    BindingHint,
    BrowserFact,
    BrowserScope,
    CoreTrace,
    CoreTraceTimeline,
    Diagnostic,
    ExecutionState,
    RejectedSettlement,
    SettlementResult,
    SkillDefinition,
    SkillManifest,
    TargetHint,
    TraceCandidate,
)
from .validators import (
    find_architecture_violations,
    validate_trace,
    validate_timeline,
    validate_timeline_payload,
)

__all__ = [
    "AcceptedSettlement",
    "ActionHint",
    "BindingHint",
    "BrowserFact",
    "BrowserScope",
    "CoreTrace",
    "CoreTraceTimeline",
    "Diagnostic",
    "ExecutionState",
    "RejectedSettlement",
    "SettlementResult",
    "SkillDefinition",
    "SkillManifest",
    "TargetHint",
    "TraceCandidate",
    "find_architecture_violations",
    "validate_trace",
    "validate_timeline",
    "validate_timeline_payload",
]
