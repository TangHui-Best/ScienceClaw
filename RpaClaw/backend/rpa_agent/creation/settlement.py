"""单 Candidate、显式 Scope、已关联 BrowserFact 的动作级结算。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
from typing import Iterable, Mapping

from pydantic import TypeAdapter, ValidationError

from ..contracts.models import (
    AcceptedSettlement,
    ActionSpec,
    BrowserFact,
    BrowserScope,
    CoreTrace,
    DataBinding,
    Diagnostic,
    RejectedSettlement,
    TargetHint,
    TargetSpec,
    TraceCandidate,
)
from ..contracts.validators import validate_trace
from .page_registry import PageRegistry


_ACTION_ADAPTER = TypeAdapter(ActionSpec)
_BINDING_ADAPTER = TypeAdapter(DataBinding)


class SettlementAttemptStatus(Enum):
    WAITING = "waiting"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass(frozen=True, slots=True)
class SettlementAttempt:
    """未形成正式 SettlementResult 的会话内短生命周期状态。"""

    candidate_id: str
    status: SettlementAttemptStatus
    reason: str


SettlementOutcome = AcceptedSettlement | RejectedSettlement | SettlementAttempt


class _SettlementRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SettlementEngine:
    def __init__(self, pages: PageRegistry) -> None:
        self._pages = pages

    def settle(
        self,
        candidate: TraceCandidate,
        *,
        facts: Iterable[BrowserFact],
        scope: BrowserScope | None,
        resolved_assets: Mapping[str, str] | None = None,
    ) -> SettlementOutcome:
        try:
            ordered_facts = self._associated_facts(candidate, facts)
        except _SettlementRejected as exc:
            return self._rejected(candidate, exc.code, exc.message)
        status = candidate.execution.status
        has_side_effect = self._has_successful_side_effect(ordered_facts)
        if status == "running":
            return SettlementAttempt(
                candidate_id=candidate.candidate_id,
                status=(
                    SettlementAttemptStatus.NEEDS_CONFIRMATION
                    if has_side_effect
                    else SettlementAttemptStatus.WAITING
                ),
                reason=(
                    "running_with_side_effect"
                    if has_side_effect
                    else "execution_running"
                ),
            )
        if status == "cancelled":
            return self._rejected(
                candidate, "execution_cancelled", "该动作已取消，未生成可回放步骤。"
            )
        if status == "failed":
            if has_side_effect:
                return SettlementAttempt(
                    candidate_id=candidate.candidate_id,
                    status=SettlementAttemptStatus.NEEDS_CONFIRMATION,
                    reason="failed_with_side_effect",
                )
            return self._rejected(
                candidate, "execution_failed", "该动作执行失败，未生成可回放步骤。"
            )
        return self._settle_succeeded(
            candidate,
            facts=ordered_facts,
            scope=scope,
            resolved_assets=resolved_assets or {},
        )

    def confirm_agent_fallback(
        self,
        candidate: TraceCandidate,
        *,
        facts: Iterable[BrowserFact],
        scope: BrowserScope | None,
        instruction: str,
        confirmed_at: datetime,
    ) -> TraceCandidate:
        try:
            ordered_facts = self._associated_facts(candidate, facts)
        except _SettlementRejected as exc:
            raise ValueError(f"settlement.agent_fallback_facts_invalid:{exc.code}") from exc
        if candidate.execution.status not in {"failed", "running"}:
            raise ValueError("settlement.agent_fallback_not_confirmable")
        if not self._has_successful_side_effect(ordered_facts):
            raise ValueError("settlement.agent_fallback_not_confirmable")
        if not instruction.strip():
            raise ValueError("settlement.agent_fallback_instruction_missing")
        try:
            self._validate_scope_availability(
                candidate.action_hint.kind, ordered_facts, scope
            )
        except _SettlementRejected as exc:
            raise ValueError("settlement.agent_fallback_scope_unresolved") from exc
        lower_bounds = [candidate.execution.started_at]
        ended_at = getattr(candidate.execution, "ended_at", None)
        if ended_at is not None:
            lower_bounds.append(ended_at)
        regressed = False
        for lower_bound in lower_bounds:
            try:
                regressed = (confirmed_at < lower_bound) or regressed
            except TypeError as exc:
                raise ValueError("settlement.agent_fallback_time_incomparable") from exc
        if regressed:
            raise ValueError("settlement.agent_fallback_time_regressed")
        target_hint = getattr(candidate.action_hint, "target_hint", None)
        action_hint: dict[str, object] = {
            "kind": "agent",
            "instruction": instruction.strip(),
        }
        if target_hint is not None:
            action_hint["target_hint"] = target_hint.model_dump(exclude_none=True)
        return TraceCandidate.model_validate({
            "candidate_id": candidate.candidate_id,
            "ordinal": candidate.ordinal,
            "origin": candidate.origin,
            "scope_hint": candidate.scope_hint.model_dump(),
            "action_hint": action_hint,
            "binding_hints": [binding.model_dump() for binding in candidate.binding_hints],
            "execution": {
                "status": "succeeded",
                "started_at": candidate.execution.started_at,
                "ended_at": confirmed_at,
                "output": candidate.execution.output,
                "error": None,
            },
        })

    def _settle_succeeded(
        self,
        candidate: TraceCandidate,
        *,
        facts: tuple[BrowserFact, ...],
        scope: BrowserScope | None,
        resolved_assets: Mapping[str, str],
    ) -> AcceptedSettlement | RejectedSettlement:
        try:
            self._validate_scope_availability(
                candidate.action_hint.kind, facts, scope
            )
            assert scope is not None
            bindings = self._bindings(candidate)
            action = self._action(candidate)
            effects = self._effects(
                candidate,
                action=action,
                bindings=bindings,
                facts=facts,
                scope=scope,
                resolved_assets=resolved_assets,
            )
            trace = CoreTrace(
                trace_id=self._trace_id(candidate.candidate_id),
                sequence=candidate.ordinal,
                scope=scope,
                action=action,
                data_bindings=bindings,
                effects=effects,
            )
            validate_trace(trace)
            return AcceptedSettlement(
                candidate_id=candidate.candidate_id,
                status="accepted",
                core_trace=trace,
            )
        except _SettlementRejected as exc:
            return self._rejected(candidate, exc.code, exc.message)
        except ValidationError as exc:
            return self._validation_rejected(candidate, exc)
        except ValueError as exc:
            return self._semantic_rejected(candidate, exc)

    @staticmethod
    def _associated_facts(
        candidate: TraceCandidate, facts: Iterable[BrowserFact]
    ) -> tuple[BrowserFact, ...]:
        supplied = tuple(facts)
        mismatched = [
            fact.fact_id
            for fact in supplied
            if fact.candidate_id not in {None, candidate.candidate_id}
        ]
        if mismatched:
            raise _SettlementRejected(
                "browser_fact_unresolved", "该动作关联到了其他步骤的浏览器事实。"
            )
        associated = [fact for fact in supplied if fact.candidate_id == candidate.candidate_id]
        fact_ids = [fact.fact_id for fact in associated]
        if len(fact_ids) != len(set(fact_ids)):
            raise _SettlementRejected(
                "browser_fact_unresolved", "该动作关联到了重复的浏览器事实。"
            )
        orders = [fact.observed_order for fact in associated]
        if len(orders) != len(set(orders)):
            raise _SettlementRejected(
                "browser_fact_unresolved", "该动作的浏览器事实顺序发生冲突。"
            )
        return tuple(sorted(associated, key=lambda fact: fact.observed_order))

    @staticmethod
    def _target(hint: TargetHint | None) -> TargetSpec:
        if hint is None or hint.name is None or not hint.locators:
            raise _SettlementRejected(
                "target_unresolved", "该动作缺少稳定、唯一的页面目标定位方式。"
            )
        payload = hint.model_dump(exclude_none=True)
        try:
            return TargetSpec.model_validate(payload)
        except ValidationError as exc:
            raise _SettlementRejected(
                "target_unresolved", "该动作的页面目标无法形成稳定定位方式。"
            ) from exc

    def _action(self, candidate: TraceCandidate):
        hint = candidate.action_hint
        kind = hint.kind
        if kind == "unsupported":
            raise _SettlementRejected(
                "action_not_replayable", "该动作暂时无法转换为受控的可回放操作。"
            )
        payload = hint.model_dump(exclude_none=True)
        target_hint = getattr(hint, "target_hint", None)
        if kind in {"click", "fill", "press", "select", "set_checked", "hover", "upload", "extract"}:
            payload.pop("target_hint", None)
            payload["target"] = self._target(target_hint).model_dump(exclude_none=True)
        elif kind in {"scroll", "agent"}:
            payload.pop("target_hint", None)
            if target_hint is not None:
                payload["target"] = self._target(target_hint).model_dump(exclude_none=True)
        if kind == "switch_page" and getattr(hint, "page_ref", None) is None:
            raise _SettlementRejected(
                "scope_unresolved", "切换页面动作没有解析出稳定 PageRef。"
            )
        try:
            return _ACTION_ADAPTER.validate_python(payload)
        except ValidationError as exc:
            raise _SettlementRejected(
                "action_not_replayable", "该动作无法形成完整的回放动作。"
            ) from exc

    @staticmethod
    def _bindings(candidate: TraceCandidate) -> list[DataBinding]:
        bindings: list[DataBinding] = []
        for hint in candidate.binding_hints:
            if hint.kind_hint is None:
                raise _SettlementRejected(
                    "binding_unresolved", f"输入输出槽位 {hint.name} 尚未确定类型。"
                )
            payload: dict[str, object] = {
                "name": hint.name,
                "direction": hint.direction,
                "kind": hint.kind_hint,
                "sensitive": hint.sensitive,
            }
            if hint.kind_hint == "literal":
                if "value" not in hint.model_fields_set:
                    raise _SettlementRejected(
                        "binding_unresolved", f"输入槽位 {hint.name} 缺少值。"
                    )
                payload["value"] = hint.value
            else:
                if hint.ref_hint is None:
                    raise _SettlementRejected(
                        "binding_unresolved", f"输入输出槽位 {hint.name} 缺少稳定引用。"
                    )
                payload["ref"] = hint.ref_hint
            try:
                bindings.append(_BINDING_ADAPTER.validate_python(payload))
            except ValidationError as exc:
                raise _SettlementRejected(
                    "binding_unresolved", f"输入输出槽位 {hint.name} 不合法。"
                ) from exc
        return bindings

    def _effects(
        self,
        candidate: TraceCandidate,
        *,
        action: object,
        bindings: list[DataBinding],
        facts: tuple[BrowserFact, ...],
        scope: BrowserScope,
        resolved_assets: Mapping[str, str],
    ) -> list[dict[str, object]]:
        action_kind = action.kind
        new_page_runtime_refs = {
            fact.runtime_scope.page_runtime_ref
            for fact in facts
            if fact.kind == "new_page"
        }
        navigation = [
            fact for fact in facts
            if fact.kind == "navigation"
            and fact.detail.is_main_frame
            and fact.runtime_scope.page_runtime_ref not in new_page_runtime_refs
        ]
        new_pages = [fact for fact in facts if fact.kind == "new_page"]
        downloads_by_ref: dict[str, BrowserFact] = {}
        dialogs = [fact for fact in facts if fact.kind == "dialog"]
        activations = [fact for fact in facts if fact.kind == "page_activated"]
        closures = [fact for fact in facts if fact.kind == "page_closed"]

        for fact in (item for item in facts if item.kind == "download"):
            previous = downloads_by_ref.get(fact.detail.download_ref)
            if previous is not None and previous.detail != fact.detail:
                raise _SettlementRejected(
                    "browser_fact_unresolved", "同一次下载出现了互相冲突的结果。"
                )
            downloads_by_ref[fact.detail.download_ref] = fact
        failed_downloads = [
            fact for fact in downloads_by_ref.values() if fact.detail.status == "failed"
        ]
        if failed_downloads:
            raise _SettlementRejected(
                "asset_unavailable", "下载没有成功完成，无法生成可回放的下载步骤。"
            )
        if len(new_pages) > 1 or len(dialogs) > 1:
            raise _SettlementRejected(
                "browser_fact_unresolved", "该动作产生了不受支持的重复浏览器副作用。"
            )

        if action_kind == "switch_page":
            if len(activations) != 1:
                raise _SettlementRejected(
                    "browser_fact_unresolved", "切换页面动作没有唯一的页面激活事实。"
                )
            activated_ref = self._resolve_page(
                activations[0].runtime_scope.page_runtime_ref,
                code="scope_unresolved",
                message="实际激活页面尚未登记，无法验证切换动作。",
            )
            if activated_ref != candidate.action_hint.page_ref:
                raise _SettlementRejected(
                    "scope_unresolved", "实际激活页面与切换目标不一致。"
                )
        elif activations:
            raise _SettlementRejected(
                "browser_fact_unresolved", "页面激活事实缺少对应的切换动作。"
            )
        if action_kind in {"close_page", "agent"}:
            if action_kind == "close_page" and len(closures) != 1:
                raise _SettlementRejected(
                    "browser_fact_unresolved", "关闭页面动作没有唯一的页面关闭事实。"
                )
            if closures:
                if len(closures) != 1:
                    raise _SettlementRejected(
                        "browser_fact_unresolved", "关闭页面事实不是唯一结果。"
                    )
                closed_ref = self._resolve_page(
                    closures[0].runtime_scope.page_runtime_ref,
                    code="scope_unresolved",
                    message="实际关闭页面尚未登记，无法验证关闭动作。",
                )
                if closed_ref != scope.page_ref:
                    raise _SettlementRejected(
                        "scope_unresolved", "实际关闭页面与动作页面不一致。"
                    )
        elif closures:
            raise _SettlementRejected(
                "browser_fact_unresolved", "页面关闭事实缺少对应的关闭动作。"
            )

        effects: list[dict[str, object]] = []
        if navigation and action_kind != "navigate":
            effects.append({"kind": "navigation"})
        if new_pages:
            page_ref = self._resolve_page(
                new_pages[0].runtime_scope.page_runtime_ref,
                code="browser_fact_unresolved",
                message="新页面尚未分配稳定 PageRef。",
            )
            effects.append({"kind": "new_page", "page_ref": page_ref})
        completed_downloads = list(downloads_by_ref.values())
        if completed_downloads:
            if len(completed_downloads) != 1:
                raise _SettlementRejected(
                    "browser_fact_unresolved", "单个动作暂不支持多个下载结果。"
                )
            fact = completed_downloads[0]
            asset_ref = resolved_assets.get(fact.detail.download_ref)
            if asset_ref is None:
                raise _SettlementRejected(
                    "asset_unavailable", "下载结果尚未形成可稳定引用的 DataAsset。"
                )
            output_bindings = [
                binding for binding in bindings
                if binding.kind == "data_asset" and binding.direction == "output"
                and binding.ref == asset_ref
            ]
            if len(output_bindings) != 1:
                raise _SettlementRejected(
                    "binding_unresolved", "下载结果没有唯一的 DataAsset 输出槽位。"
                )
            effects.append({"kind": "download", "binding": output_bindings[0].name})
        if dialogs:
            fact = dialogs[0]
            effect: dict[str, object] = {
                "kind": "dialog",
                "dialog_type": fact.detail.dialog_type,
                "response": fact.detail.response,
            }
            if fact.detail.dialog_type == "prompt" and fact.detail.response == "accept":
                candidates = self._prompt_bindings(action, bindings)
                if len(candidates) > 1:
                    raise _SettlementRejected(
                        "binding_unresolved", "Prompt 输入存在多个可用槽位，无法唯一映射。"
                    )
                if not candidates:
                    if fact.detail.prompt_value is not None:
                        raise _SettlementRejected(
                            "binding_unresolved", "Prompt 输入没有可用的输入槽位。"
                        )
                else:
                    candidate_binding = candidates[0]
                    if candidate_binding.sensitive and candidate_binding.kind != "secret":
                        raise _SettlementRejected(
                            "binding_unresolved", "敏感 Prompt 输入必须映射为 Secret。"
                        )
                    effect["input_binding"] = candidate_binding.name
            effects.append(effect)

        kinds = [effect["kind"] for effect in effects]
        if len(kinds) > 1 and kinds != ["new_page", "download"]:
            raise _SettlementRejected(
                "browser_fact_unresolved", "该动作产生了 v0.1 白名单之外的复合副作用。"
            )
        return effects

    @staticmethod
    def _prompt_bindings(action: object, bindings: list[DataBinding]) -> list[DataBinding]:
        """按结构槽位找 Prompt 输入，不比较录制值。"""

        consumed: set[str] = set()
        slot_by_action = {
            "navigate": "url",
            "fill": "value",
            "press": "keys",
            "select": "option",
            "upload": "file",
        }
        slot = slot_by_action.get(action.kind)
        if slot is not None:
            consumed.add(slot)
        target = getattr(action, "target", None)
        for step in (target.path or []) if target is not None else []:
            if step.filter_binding is not None:
                consumed.add(step.filter_binding)
        return [
            binding for binding in bindings
            if binding.direction == "input"
            and binding.kind in {"literal", "skill_input", "variable", "secret"}
            and binding.name not in consumed
        ]

    def _resolve_page(self, runtime_page_ref: str, *, code: str, message: str) -> str:
        try:
            return self._pages.resolve(runtime_page_ref)
        except ValueError as exc:
            raise _SettlementRejected(code, message) from exc

    def _validate_scope_availability(
        self,
        action_kind: str,
        facts: tuple[BrowserFact, ...],
        scope: BrowserScope | None,
    ) -> None:
        if scope is None:
            raise _SettlementRejected(
                "scope_unresolved", "无法确定该动作所在的稳定页面或 iframe。"
            )
        closures = [fact for fact in facts if fact.kind == "page_closed"]
        if self._pages.has_page_ref(scope.page_ref, include_closed=False):
            if action_kind == "close_page":
                raise _SettlementRejected(
                    "scope_unresolved", "关闭动作引用的页面尚未登记为已关闭。"
                )
            if action_kind == "agent" and closures:
                raise _SettlementRejected(
                    "browser_fact_unresolved", "页面关闭事实与当前打开页面状态冲突。"
                )
            return
        if not self._pages.has_page_ref(scope.page_ref, include_closed=True):
            raise _SettlementRejected(
                "scope_unresolved", "该动作引用的页面尚未登记。"
            )
        if action_kind not in {"close_page", "agent"}:
            raise _SettlementRejected(
                "scope_unresolved", "该动作引用的页面已经关闭。"
            )
        if len(closures) != 1:
            raise _SettlementRejected(
                "browser_fact_unresolved", "关闭页面动作没有唯一的页面关闭事实。"
            )
        closed_ref = self._resolve_page(
            closures[0].runtime_scope.page_runtime_ref,
            code="scope_unresolved",
            message="实际关闭页面尚未登记，无法验证关闭动作。",
        )
        if closed_ref != scope.page_ref:
            raise _SettlementRejected(
                "scope_unresolved", "实际关闭页面与动作页面不一致。"
            )

    @staticmethod
    def _validation_rejected(
        candidate: TraceCandidate, error: ValidationError
    ) -> RejectedSettlement:
        locations = {
            str(part)
            for item in error.errors(include_url=False)
            for part in item.get("loc", ())
        }
        if "scope" in locations:
            code = "scope_unresolved"
            message = "该动作的页面作用域不完整，无法生成可回放步骤。"
        elif "target" in locations:
            code = "target_unresolved"
            message = "该动作的目标定位不完整，无法生成可回放步骤。"
        elif "data_bindings" in locations:
            code = "binding_unresolved"
            message = "该动作的输入输出不完整，无法生成可回放步骤。"
        elif "effects" in locations:
            code = "browser_fact_unresolved"
            message = "该动作的浏览器副作用不完整，无法生成可回放步骤。"
        else:
            code = "action_not_replayable"
            message = "该动作无法形成完整的回放动作。"
        return SettlementEngine._rejected(candidate, code, message)

    @staticmethod
    def _semantic_rejected(
        candidate: TraceCandidate, error: ValueError
    ) -> RejectedSettlement:
        prefix = str(error).split(":", 1)[0]
        if prefix.startswith("binding") or prefix.startswith("trace.binding"):
            code = "binding_unresolved"
            message = "该动作的输入输出契约不完整，无法生成可回放步骤。"
        elif prefix.startswith("effect"):
            code = "browser_fact_unresolved"
            message = "该动作的浏览器副作用发生冲突，无法生成可回放步骤。"
        elif prefix.startswith("scope") or prefix.startswith("page"):
            code = "scope_unresolved"
            message = "该动作的页面作用域无法解析。"
        elif prefix.startswith("target"):
            code = "target_unresolved"
            message = "该动作的目标定位无法解析。"
        else:
            code = "action_not_replayable"
            message = "该动作无法形成完整的回放动作。"
        return SettlementEngine._rejected(candidate, code, message)

    @staticmethod
    def _has_successful_side_effect(facts: tuple[BrowserFact, ...]) -> bool:
        return any(
            fact.kind in {"navigation", "new_page", "dialog", "page_activated", "page_closed"}
            or (fact.kind == "download" and fact.detail.status == "completed")
            for fact in facts
        )

    @staticmethod
    def _trace_id(candidate_id: str) -> str:
        digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:24]
        return f"trace_{digest}"

    @staticmethod
    def _rejected(
        candidate: TraceCandidate, code: str, message: str
    ) -> RejectedSettlement:
        return RejectedSettlement(
            candidate_id=candidate.candidate_id,
            status="rejected",
            diagnostic=Diagnostic(code=code, message=message),
        )
