"""Trace 级执行包装、select 语义与显式 Wait。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import re

from .effects import EffectCoordinator
from .locators import LocatorResolutionError, LocatorResolver
from .results import ResultBuilder, RuntimeServiceError, StepExecutionError


class StepExecutor:
    def __init__(self, run_id: str, effects: EffectCoordinator, results: ResultBuilder) -> None:
        self._run_id = run_id
        self._effects = effects
        self._results = results

    async def execute(
        self,
        *,
        trace_id: str,
        sequence: int,
        action_kind: str,
        operation: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            await operation()
        except BaseException as exc:
            cleanup_diagnostics = await self._effects.cleanup_active(exc)
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            self._results.record_step(trace_id, sequence, action_kind, status)
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                _attach_cleanup_diagnostics(exc, cleanup_diagnostics)
                raise
            if isinstance(exc, StepExecutionError):
                _attach_cleanup_diagnostics(exc, cleanup_diagnostics)
                raise
            if isinstance(exc, RuntimeServiceError):
                phase, code, message = exc.phase, exc.code, exc.safe_message
            else:
                phase, code, message = "action", "action.failed", "浏览器动作执行失败"
            outward = StepExecutionError(
                run_id=self._run_id,
                trace_id=trace_id,
                sequence=sequence,
                action_kind=action_kind,
                phase=phase,
                code=code,
                safe_message=message,
            )
            _attach_cleanup_diagnostics(outward, cleanup_diagnostics)
            raise outward from exc
        self._results.record_step(trace_id, sequence, action_kind, "succeeded")

    async def select_option(self, *, target: object, option: str) -> None:
        try:
            options = await target.evaluate(
                "element => Array.from(element.options).map(option => ({value: option.value, label: option.label}))"
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            raise RuntimeServiceError(
                phase="input", code="select.inspect_failed", safe_message="读取下拉选项失败"
            ) from exc
        if not isinstance(options, list) or any(not isinstance(item, dict) for item in options):
            raise RuntimeServiceError(
                phase="input", code="select.options_invalid", safe_message="下拉选项结构无效"
            )
        value_matches = [item for item in options if item.get("value") == option]
        if len(value_matches) == 1:
            await target.select_option(value=option)
            return
        if len(value_matches) > 1:
            raise RuntimeServiceError(
                phase="input", code="select.option_ambiguous", safe_message="下拉 value 存在多个匹配"
            )
        label_matches = [item for item in options if item.get("label") == option]
        if len(label_matches) == 1:
            await target.select_option(label=option)
            return
        code = "select.option_ambiguous" if len(label_matches) > 1 else "select.option_not_found"
        raise RuntimeServiceError(phase="input", code=code, safe_message="下拉选项无法唯一匹配")

    async def extract_table(self, *, target: object, columns: list[dict[str, object]]) -> object:
        return await target.evaluate(
            "(table, columns) => ({columns, rows: Array.from(table.rows).map(row => Array.from(row.cells).map(cell => cell.innerText))})",
            columns,
        )


class WaitExecutor:
    def __init__(
        self,
        locators: LocatorResolver,
        *,
        expect_factory: Callable[[object], object] | None = None,
    ) -> None:
        self._locators = locators
        self._expect_factory = expect_factory

    async def until(self, *, scope: object, conditions: list[object]) -> None:
        if not conditions:
            raise RuntimeServiceError(
                phase="wait", code="wait.conditions_required", safe_message="Wait 必须包含显式条件"
            )
        for raw in conditions:
            try:
                condition = (
                    raw
                    if isinstance(raw, dict)
                    else raw.model_dump(mode="python", exclude_none=True)
                )
                await self._until_one(scope, condition)
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                raise
            except LocatorResolutionError as exc:
                raise RuntimeServiceError(
                    phase="wait",
                    code="wait.target_resolution_failed",
                    safe_message="Wait Target 无法唯一解析",
                ) from exc
            except RuntimeServiceError as exc:
                if exc.phase == "wait":
                    raise
                raise RuntimeServiceError(
                    phase="wait",
                    code="wait.condition_failed",
                    safe_message="Wait 条件执行失败",
                ) from exc
            except Exception as exc:
                raise RuntimeServiceError(
                    phase="wait",
                    code="wait.condition_failed",
                    safe_message="Wait 条件未在期限内满足",
                ) from exc

    async def _until_one(self, scope: object, condition: dict[str, Any]) -> None:
        kind = condition.get("kind")
        if kind == "element_state":
            target = await self._locators.resolve(scope=scope, target=condition["target"])
            state = condition["state"]
            if state in {"visible", "hidden"}:
                await target.wait_for(state=state)
                return
            assertion = self._expect(target)
            if state == "enabled":
                await assertion.to_be_enabled()
            elif state == "disabled":
                await assertion.to_be_disabled()
            elif state == "checked":
                await assertion.to_be_checked()
            elif state == "unchecked":
                await assertion.to_be_checked(checked=False)
            else:
                raise RuntimeServiceError(
                    phase="wait", code="wait.state_unsupported", safe_message="Wait state 不受支持"
                )
            return
        if kind in {"element_text", "element_value"}:
            target = await self._locators.resolve(scope=scope, target=condition["target"])
            await self._expect_element(target, condition, value_kind=kind)
            return
        if kind == "url_matches":
            expected = _expected_argument(condition, contains_as_regex=True)
            await self._expect(_page_for_url(scope)).to_have_url(expected)
            return
        raise RuntimeServiceError(
            phase="wait", code="wait.kind_unsupported", safe_message="Wait kind 不受支持"
        )

    async def _expect_element(
        self,
        target: object,
        condition: dict[str, Any],
        *,
        value_kind: str,
    ) -> None:
        operator = condition.get("operator")
        expected = _expected_argument(condition, contains_as_regex=value_kind == "element_value")
        assertion = self._expect(target)
        if value_kind == "element_text" and operator == "contains":
            await assertion.to_contain_text(expected)
        elif value_kind == "element_text":
            await assertion.to_have_text(expected)
        else:
            await assertion.to_have_value(expected)

    def _expect(self, subject: object) -> object:
        factory = self._expect_factory or _default_expect
        return factory(subject)


def _expected_argument(
    condition: dict[str, Any],
    *,
    contains_as_regex: bool,
) -> str | re.Pattern[str]:
    expected = condition.get("expected")
    if not isinstance(expected, str):
        raise RuntimeServiceError(
            phase="wait", code="wait.expected_missing", safe_message="Wait expected 未解析"
        )
    operator = condition.get("operator")
    if operator == "exact":
        return expected
    if operator == "contains":
        return re.compile(re.escape(expected)) if contains_as_regex else expected
    if operator == "regex":
        try:
            return re.compile(expected)
        except re.error as exc:
            raise RuntimeServiceError(
                phase="wait", code="wait.regex_invalid", safe_message="Wait regex 无效"
            ) from exc
    raise RuntimeServiceError(
        phase="wait", code="wait.operator_invalid", safe_message="Wait operator 不受支持"
    )


def _page_for_url(scope: object) -> object:
    page = getattr(scope, "page", None)
    if page is None:
        return scope
    return page() if callable(page) else page


def _default_expect(subject: object) -> object:
    try:
        from playwright.async_api import expect as playwright_expect
    except Exception as exc:
        raise RuntimeServiceError(
            phase="wait",
            code="wait.runtime_unavailable",
            safe_message="Playwright expect 不可用",
        ) from exc
    return playwright_expect(subject)


def _attach_cleanup_diagnostics(
    error: BaseException,
    diagnostics: tuple[RuntimeServiceError, ...],
) -> None:
    if diagnostics and "effect.cleanup_failed" not in getattr(error, "__notes__", ()):
        error.add_note("effect.cleanup_failed")
