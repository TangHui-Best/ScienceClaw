"""Use causal browser facts to freeze a manual draft, without consuming legacy timelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

from ..contracts.models import (
    AcceptedSettlement,
    BrowserFact,
    BrowserScope,
    RejectedSettlement,
    TraceCandidate,
)
from ..creation.settlement import SettlementAttempt, SettlementOutcome

from .session import RecordingSession


class ManualSettlementPort(Protocol):
    def settle(
        self,
        candidate: TraceCandidate,
        *,
        facts: Iterable[BrowserFact],
        scope: BrowserScope | None,
        resolved_assets: Mapping[str, str] | None = None,
    ) -> SettlementOutcome: ...


@dataclass(frozen=True)
class ManualDraftSettlement:
    state: str
    trace_id: str | None = None
    diagnostic_code: str | None = None


class ManualFactFreezer:
    """The only route from manual candidate/facts to a vNext CoreTrace."""

    def __init__(self, settlement: ManualSettlementPort) -> None:
        self._settlement = settlement

    def settle_draft(
        self,
        *,
        session: RecordingSession,
        draft_id: str,
        candidate: TraceCandidate,
        facts: Iterable[BrowserFact],
        scope: BrowserScope | None,
        resolved_assets: Mapping[str, str] | None = None,
    ) -> ManualDraftSettlement:
        outcome = self._settlement.settle(
            candidate,
            facts=facts,
            scope=scope,
            resolved_assets=resolved_assets,
        )
        if isinstance(outcome, AcceptedSettlement):
            session.freeze_manual_trace(draft_id=draft_id, trace=outcome.core_trace)
            return ManualDraftSettlement(
                state="frozen", trace_id=outcome.core_trace.trace_id
            )
        if isinstance(outcome, RejectedSettlement):
            session.invalidate_manual_draft(
                draft_id=draft_id, diagnostic_code=outcome.diagnostic.code
            )
            return ManualDraftSettlement(
                state="invalid", diagnostic_code=outcome.diagnostic.code
            )
        if isinstance(outcome, SettlementAttempt):
            session.mark_manual_draft_enriching(
                draft_id=draft_id, diagnostic_code=outcome.reason
            )
            return ManualDraftSettlement(
                state="enriching", diagnostic_code=outcome.reason
            )
        raise ValueError("next_recording.manual_settlement_invalid")
