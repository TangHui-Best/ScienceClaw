"""Strict unique locator resolution with bounded Playwright auto-wait."""

from __future__ import annotations

import asyncio
from typing import Any

from .results import RuntimeServiceError


class LocatorResolutionError(RuntimeServiceError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(phase="target", code=code, safe_message=message)


class LocatorResolver:
    def __init__(self, *, auto_wait_timeout_s: float = 5.0) -> None:
        if (
            not isinstance(auto_wait_timeout_s, (int, float))
            or isinstance(auto_wait_timeout_s, bool)
            or auto_wait_timeout_s <= 0
        ):
            raise ValueError("locator.auto_wait_timeout_invalid")
        self._auto_wait_timeout_s = float(auto_wait_timeout_s)

    async def resolve(self, *, scope: object, target: object) -> object:
        payload = _payload(target)
        current = scope
        for step in payload.get("path", []):
            if "filter_binding" in step:
                raise LocatorResolutionError(
                    "locator.filter_binding_unresolved",
                    "Target filter_binding 必须在编译产物中显式解析",
                )
            filter_text = step.get("filter_text")
            current = await self._resolve_candidates(
                current,
                step.get("locators", []),
                filter_text=str(filter_text) if filter_text is not None else None,
                index=step.get("index"),
            )
        return await self._resolve_candidates(
            current,
            payload.get("locators", []),
            index=payload.get("index"),
        )

    async def resolve_locator_specs(self, scope: object, locators: list[object]) -> object:
        return await self._resolve_candidates(scope, locators)

    async def _resolve_candidates(
        self,
        scope: object,
        locators: list[object],
        *,
        filter_text: str | None = None,
        index: object = None,
    ) -> object:
        ambiguous = False
        index_out_of_range = False
        zero_candidates: list[object] = []
        for raw in locators:
            locator = _make_locator(scope, _payload(raw))
            if filter_text is not None:
                locator = locator.filter(has_text=filter_text)
            count = await locator.count()
            if index is not None:
                if isinstance(index, int) and 0 <= index < count:
                    selected = getattr(locator, "nth")(index)
                    if await selected.count() == 1:
                        return selected
                if count > 0:
                    index_out_of_range = True
                else:
                    zero_candidates.append(locator)
                continue
            if count == 1:
                return locator
            if count > 1:
                ambiguous = True
            else:
                zero_candidates.append(locator)

        if zero_candidates:
            dynamic, dynamic_ambiguous, dynamic_index_out = await self._bounded_auto_wait(
                zero_candidates,
                index=index,
            )
            if dynamic is not None:
                return dynamic
            ambiguous = ambiguous or dynamic_ambiguous
            index_out_of_range = index_out_of_range or dynamic_index_out
        if ambiguous:
            raise LocatorResolutionError("locator.ambiguous", "所有 Locator 候选均无法唯一定位")
        if index_out_of_range:
            raise LocatorResolutionError(
                "locator.index_out_of_range", "显式 index 超出所有 Locator 候选的匹配范围"
            )
        raise LocatorResolutionError("locator.not_found", "所有 Locator 候选均无匹配")

    async def _bounded_auto_wait(
        self,
        candidates: list[object],
        *,
        index: object,
    ) -> tuple[object | None, bool, bool]:
        awaited = asyncio.create_task(self._wait_for_unique(candidates, index=index))
        try:
            return await asyncio.wait_for(
                asyncio.shield(awaited), timeout=self._auto_wait_timeout_s
            )
        except TimeoutError:
            # An inner locator TimeoutError is a real browser error and must
            # propagate; only the outer bounded deadline becomes "no match".
            if awaited.done():
                return await awaited
            awaited.cancel()
            await asyncio.gather(awaited, return_exceptions=True)
            return None, False, False
        except BaseException:
            if not awaited.done():
                awaited.cancel()
                await asyncio.gather(awaited, return_exceptions=True)
            raise

    async def _wait_for_unique(
        self,
        candidates: list[object],
        *,
        index: object,
    ) -> tuple[object | None, bool, bool]:
        tasks = {
            asyncio.create_task(locator.wait_for(state="attached")): (order, locator)
            for order, locator in enumerate(candidates)
        }
        ambiguous = False
        index_out_of_range = False
        try:
            while tasks:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in sorted(done, key=lambda item: tasks[item][0]):
                    _, locator = tasks.pop(task)
                    task.result()
                    count = await locator.count()
                    if index is not None:
                        if isinstance(index, int) and 0 <= index < count:
                            selected = getattr(locator, "nth")(index)
                            if await selected.count() == 1:
                                return selected, ambiguous, index_out_of_range
                        if count > 0:
                            index_out_of_range = True
                        continue
                    if count == 1:
                        return locator, ambiguous, index_out_of_range
                    if count > 1:
                        ambiguous = True
            return None, ambiguous, index_out_of_range
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python", exclude_none=True)
    raise LocatorResolutionError(
        "locator.spec_invalid", "LocatorSpec 必须是受控字典或契约对象"
    )


def _make_locator(scope: object, spec: dict[str, Any]) -> object:
    strategy = spec.get("strategy")
    exact = spec.get("exact", True)
    if strategy == "role":
        return scope.get_by_role(spec["role"], name=spec.get("name"), exact=exact)
    if strategy == "test_id":
        return scope.get_by_test_id(spec["value"])
    if strategy == "label":
        return scope.get_by_label(spec["value"], exact=exact)
    if strategy == "placeholder":
        return scope.get_by_placeholder(spec["value"], exact=exact)
    if strategy == "text":
        return scope.get_by_text(spec["value"], exact=exact)
    if strategy == "title":
        return scope.get_by_title(spec["value"], exact=exact)
    if strategy == "alt_text":
        return scope.get_by_alt_text(spec["value"], exact=exact)
    if strategy in {"css", "xpath"}:
        return scope.locator(spec["value"])
    raise LocatorResolutionError("locator.strategy_invalid", "Locator strategy 不受支持")
