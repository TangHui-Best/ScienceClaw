from __future__ import annotations

from typing import Any, Dict, List

from .contract_models import StepContract
from .contract_pipeline import CommittedStep
from .contract_skill_builder import build_contract_skill_files


def session_contract_committed_steps(session: Any) -> List[CommittedStep]:
    committed: List[CommittedStep] = []
    for item in getattr(session, "contract_steps", []) or []:
        if not isinstance(item, dict):
            continue
        contract_payload = item.get("contract")
        artifact = item.get("artifact")
        if not isinstance(contract_payload, dict) or not isinstance(artifact, dict):
            continue
        committed.append(
            CommittedStep(
                contract=StepContract(**contract_payload),
                artifact=dict(artifact),
                validation_evidence=dict(item.get("validation_evidence") or {}),
            )
        )
    return committed


def build_contract_skill_files_from_session(
    session: Any,
    skill_name: str,
    description: str,
) -> Dict[str, str]:
    committed_steps = session_contract_committed_steps(session)
    return build_contract_skill_files(skill_name, description, committed_steps)


def has_contract_steps(session: Any) -> bool:
    return bool(session_contract_committed_steps(session))
