"""RPA Agent 创建态采集组件。"""

from .candidate_registry import (
    ActiveCandidateRegistry,
    CandidateReservation,
    LockedCandidate,
)
from .browser_facts import BrowserFactObserver, FactBuffer, FactTrigger
from .manual_aggregator import (
    InteractionKind,
    ManualEvent,
    ManualEventKind,
    ManualInteractionAggregator,
)
from .page_registry import PageRegistry
from .projection import (
    CreationStepRow,
    ProjectionStatus,
    project_creation_steps,
)
from .readiness import (
    BuildReadiness,
    ReadinessCode,
    ReadinessIssue,
    derive_build_readiness,
)
from .settlement import SettlementAttempt, SettlementAttemptStatus, SettlementEngine
from .session import (
    AgentCandidateReservation,
    ControlMode,
    SessionVariableStore,
    SkillCreationSession,
)
from .timeline import TimelineStore

__all__ = [
    "ActiveCandidateRegistry",
    "AgentCandidateReservation",
    "BrowserFactObserver",
    "BuildReadiness",
    "CandidateReservation",
    "ControlMode",
    "CreationStepRow",
    "FactBuffer",
    "FactTrigger",
    "InteractionKind",
    "LockedCandidate",
    "ManualEvent",
    "ManualEventKind",
    "ManualInteractionAggregator",
    "PageRegistry",
    "ProjectionStatus",
    "ReadinessCode",
    "ReadinessIssue",
    "SettlementAttempt",
    "SettlementAttemptStatus",
    "SettlementEngine",
    "SessionVariableStore",
    "SkillCreationSession",
    "TimelineStore",
    "derive_build_readiness",
    "project_creation_steps",
]
