from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from backend.rpa.harness.artifact_store import RPAHarnessArtifactStore
from backend.rpa.harness.packets import (
    FailurePacket,
    RPAHarnessArtifactRef,
    RPAHarnessStage,
)


logger = logging.getLogger(__name__)


def capture_rpa_failure_packet(
    *,
    session_id: str,
    stage: RPAHarnessStage,
    failure_type: str,
    artifact_root: str | Path | None = None,
    max_packets_per_kind: int | None = None,
    step_id: Optional[str] = None,
    user_instruction: Optional[str] = None,
    current_url: str = "",
    current_title: str = "",
    failed_plan: Optional[Dict[str, Any]] = None,
    raw_error: Any = None,
    snapshot_after_failure: Any = None,
    compact_snapshot: Any = None,
    repair_input: Any = None,
    repair_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Path]:
    root = _resolve_artifact_root(artifact_root)
    if not root:
        return None

    try:
        store = RPAHarnessArtifactStore(
            root=root,
            max_packets_per_kind=_resolve_max_packets(max_packets_per_kind),
        )
        packet = FailurePacket(
            session_id=session_id,
            step_id=step_id,
            stage=stage,
            failure_type=failure_type,
            user_instruction=user_instruction,
            current_url=current_url,
            current_title=current_title,
            failed_plan_summary=_plan_summary(failed_plan),
            metadata=dict(metadata or {}),
        )

        if raw_error is not None:
            packet.raw_error_ref = store.write_packet_artifact(
                packet.packet_kind,
                packet.packet_id,
                "raw_error.json",
                raw_error,
            )
        failed_code_ref = _write_failed_code(store, packet, failed_plan)
        if failed_code_ref is not None:
            packet.failed_code_ref = failed_code_ref
        if snapshot_after_failure is not None:
            packet.snapshot_after_failure_ref = store.write_packet_artifact(
                packet.packet_kind,
                packet.packet_id,
                "snapshot_after_failure.json",
                snapshot_after_failure,
            )
        if compact_snapshot is not None:
            packet.compact_snapshot_ref = store.write_packet_artifact(
                packet.packet_kind,
                packet.packet_id,
                "compact_snapshot.json",
                compact_snapshot,
            )
        if repair_input is not None:
            packet.repair_input_ref = store.write_packet_artifact(
                packet.packet_kind,
                packet.packet_id,
                "repair_input.json",
                repair_input,
            )
        if repair_output is not None:
            packet.repair_output_ref = store.write_packet_artifact(
                packet.packet_kind,
                packet.packet_id,
                "repair_output.json",
                repair_output,
            )

        return store.write_packet(packet)
    except Exception:
        logger.warning("[RPA-HARNESS] failure packet capture failed", exc_info=True)
        return None


def _write_failed_code(
    store: RPAHarnessArtifactStore,
    packet: FailurePacket,
    failed_plan: Optional[Dict[str, Any]],
) -> Optional[RPAHarnessArtifactRef]:
    if not isinstance(failed_plan, dict):
        return None
    code = str(failed_plan.get("code") or "")
    if not code:
        return None
    return store.write_packet_artifact(
        packet.packet_kind,
        packet.packet_id,
        "failed_code.py",
        code,
        media_type="text/x-python",
    )


def _resolve_artifact_root(artifact_root: str | Path | None) -> str:
    if artifact_root is not None and not str(artifact_root).strip():
        return ""
    explicit = str(artifact_root or "").strip()
    if explicit:
        return explicit

    env_root = str(os.environ.get("RPA_HARNESS_ARTIFACT_DIR") or "").strip()
    if env_root:
        return env_root

    try:
        from backend.config import settings

        return str(getattr(settings, "rpa_harness_artifact_dir", "") or "").strip()
    except Exception:
        return ""


def _resolve_max_packets(max_packets_per_kind: int | None) -> int:
    if max_packets_per_kind is not None:
        return max(1, int(max_packets_per_kind))
    env_value = str(os.environ.get("RPA_HARNESS_MAX_FAILURE_PACKETS") or "").strip()
    if env_value:
        return max(1, int(env_value))
    try:
        from backend.config import settings

        return max(1, int(getattr(settings, "rpa_harness_max_failure_packets", 100)))
    except Exception:
        return 100


def _plan_summary(plan: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(plan, dict):
        return None
    description = str(plan.get("description") or "").strip()
    if description:
        return description
    action_type = str(plan.get("action_type") or "").strip()
    return action_type or None
