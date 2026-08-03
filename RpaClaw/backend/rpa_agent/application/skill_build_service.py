"""Application boundary between a Next recording session and a new Skill artifact."""

from __future__ import annotations

from dataclasses import dataclass

from ..skill_build import CompiledSkill, IndependentSkillReplayer, SkillBuildConfig, compile_skill
from .session_orchestrator import RpaAgentNextSessionOrchestrator


class SkillNotFoundError(ValueError):
    code = "rpa_agent_next.skill_not_found"


class SkillOwnerError(ValueError):
    code = "rpa_agent_next.skill_not_owned"


@dataclass(frozen=True)
class _OwnedSkill:
    owner_id: str
    artifact: CompiledSkill


class RpaAgentNextSkillBuildService:
    """Keeps only new artifacts in a process-local registry for the S3 harness.

    Persistence/governance is deliberately deferred to S4.  This service cannot
    look up the legacy Skill storage because it receives source only via the
    Next session orchestrator.
    """

    def __init__(
        self,
        *,
        sessions: RpaAgentNextSessionOrchestrator,
        replayer: IndependentSkillReplayer,
    ) -> None:
        self._sessions = sessions
        self._replayer = replayer
        self._skills: dict[str, _OwnedSkill] = {}

    async def build(
        self,
        *,
        session_id: str,
        owner_id: str,
        config: SkillBuildConfig,
    ) -> CompiledSkill:
        timeline = await self._sessions.timeline(
            session_id=session_id, owner_id=owner_id
        )
        artifact = compile_skill(timeline, config)
        existing = self._skills.get(artifact.skill_id)
        if existing is not None and existing.owner_id != owner_id:
            raise SkillOwnerError(artifact.skill_id)
        self._skills[artifact.skill_id] = _OwnedSkill(owner_id, artifact)
        return artifact

    async def replay(
        self,
        *,
        skill_id: str,
        owner_id: str,
        inputs: dict[str, object],
    ):
        owned = self._skills.get(skill_id)
        if owned is None:
            raise SkillNotFoundError(skill_id)
        if owned.owner_id != owner_id:
            raise SkillOwnerError(skill_id)
        return await self._replayer.replay(
            skill=owned.artifact, owner_id=owner_id, inputs=inputs
        )
