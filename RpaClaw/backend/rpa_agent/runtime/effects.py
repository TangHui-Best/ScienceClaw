"""在动作前安装、动作后结算的浏览器 Effect 协调器。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
from typing import Any

from .pages import PageRegistry
from .results import RuntimeServiceError
from .variables import DataAssetHandle, DataAssetRegistry


@dataclass(slots=True)
class _PreparedEffect:
    spec: dict[str, Any]
    manager: object | None = None
    entered: object | None = None
    event_future: asyncio.Future[object] | None = None
    listeners: list[tuple[object, str, object]] = field(default_factory=list)
    manager_finished: bool = False


@dataclass(slots=True)
class EffectHandle:
    scope: object
    page: object
    prepared: list[_PreparedEffect] = field(default_factory=list)
    state: str = "prepared"


class EffectCoordinator:
    _ALLOWED = frozenset({"navigation", "new_page", "download", "dialog"})

    def __init__(self, pages: PageRegistry, assets: DataAssetRegistry) -> None:
        self._pages = pages
        self._assets = assets
        self._active: dict[int, EffectHandle] = {}

    async def prepare(self, *, scope: object, effects: list[object]) -> EffectHandle:
        specs = [_payload(item) for item in effects]
        kinds = [item.get("kind") for item in specs]
        if any(kind not in self._ALLOWED for kind in kinds):
            raise RuntimeServiceError(
                phase="effect_prepare", code="effect.unsupported", safe_message="Effect kind 不受支持"
            )
        if len(kinds) > 1 and kinds != ["new_page", "download"]:
            raise RuntimeServiceError(
                phase="effect_prepare", code="effect.combination_unsupported", safe_message="Effect 组合不受支持"
            )
        if len(kinds) != len(set(kinds)):
            raise RuntimeServiceError(
                phase="effect_prepare", code="effect.duplicate", safe_message="Effect kind 不得重复"
            )
        page = _owning_page(scope)
        handle = EffectHandle(scope=scope, page=page)
        if not specs:
            self._active[id(handle)] = handle
            return handle
        try:
            if kinds == ["new_page", "download"]:
                context = _page_context(page)
                download_observer = self._install_new_page_download(context, specs[1])
                handle.prepared.append(download_observer)
                new_page_observer = await self._install(page, specs[0])
                handle.prepared.insert(0, new_page_observer)
            else:
                for spec in specs:
                    prepared = await self._install(page, spec)
                    handle.prepared.append(prepared)
        except BaseException as exc:
            diagnostics = await self._cleanup(handle, exc)
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                _attach_cleanup_diagnostics(exc, diagnostics)
                raise
            if isinstance(exc, RuntimeServiceError):
                _attach_cleanup_diagnostics(exc, diagnostics)
                raise
            outward = RuntimeServiceError(
                phase="effect_prepare", code="effect.prepare_failed", safe_message="Effect 监听安装失败"
            )
            _attach_cleanup_diagnostics(outward, diagnostics)
            raise outward from exc
        self._active[id(handle)] = handle
        return handle

    async def _install(self, page: object, spec: dict[str, Any]) -> _PreparedEffect:
        kind = spec["kind"]
        if kind == "navigation":
            manager = page.expect_navigation()
            entered = await manager.__aenter__()
            return _PreparedEffect(spec, manager, entered)
        if kind == "new_page":
            context = _page_context(page)
            manager = context.expect_page()
            entered = await manager.__aenter__()
            return _PreparedEffect(spec, manager, entered)
        if kind == "download":
            manager = page.expect_download()
            entered = await manager.__aenter__()
            return _PreparedEffect(spec, manager, entered)
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()

        def handler(dialog: object) -> None:
            task = asyncio.create_task(self._handle_dialog(dialog, spec))

            def completed(result: asyncio.Task[object]) -> None:
                try:
                    outcome = result.result()
                except asyncio.CancelledError as exc:
                    if not future.done():
                        future.set_exception(exc)
                except BaseException:
                    if not future.done():
                        future.set_exception(
                            RuntimeServiceError(
                                phase="effect_commit",
                                code="effect.dialog_failed",
                                safe_message="Dialog 处理失败",
                            )
                        )
                else:
                    if not future.done():
                        future.set_result(outcome)

            task.add_done_callback(completed)

        page.on("dialog", handler)
        return _PreparedEffect(spec, event_future=future, listeners=[(page, "dialog", handler)])

    def _install_new_page_download(
        self,
        context: object,
        spec: dict[str, Any],
    ) -> _PreparedEffect:
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        prepared = _PreparedEffect(spec, event_future=future)

        def download_handler(download: object) -> None:
            if not future.done():
                future.set_result(download)

        def page_handler(page: object) -> None:
            page.on("download", download_handler)
            prepared.listeners.append((page, "download", download_handler))

        context.on("page", page_handler)
        prepared.listeners.append((context, "page", page_handler))
        return prepared

    async def _handle_dialog(self, dialog: object, spec: dict[str, Any]) -> object:
        actual_type = getattr(dialog, "type")
        if callable(actual_type):
            actual_type = actual_type()
        if actual_type != spec.get("dialog_type"):
            raise RuntimeError("dialog type mismatch")
        if spec.get("response") == "accept":
            await dialog.accept(spec.get("input_value")) if "input_value" in spec else await dialog.accept()
        else:
            await dialog.dismiss()
        return dialog

    async def commit(self, handle: EffectHandle) -> None:
        if id(handle) not in self._active or handle.state != "prepared":
            raise RuntimeServiceError(
                phase="effect_commit", code="effect.handle_invalid", safe_message="Effect handle 已失效"
            )
        try:
            for item in handle.prepared:
                value = await self._finish(item)
                kind = item.spec["kind"]
                if kind == "new_page":
                    self._pages.register(item.spec["page_ref"], value)
                elif kind == "download":
                    asset_ref = item.spec.get("asset_ref")
                    if not asset_ref:
                        raise RuntimeError("download asset_ref missing")
                    path = await _maybe_await(value.path())
                    name = getattr(value, "suggested_filename", None)
                    if callable(name):
                        name = name()
                    self._assets.register(
                        asset_ref,
                        DataAssetHandle(asset_ref, path, {"name": name} if name else {}),
                    )
            listener_diagnostics = await self._remove_listeners(handle)
            if listener_diagnostics:
                cleanup_failure = RuntimeServiceError(
                    phase="effect_commit",
                    code="effect.cleanup_failed",
                    safe_message="Effect 监听清理失败",
                )
                _attach_cleanup_diagnostics(cleanup_failure, listener_diagnostics)
                raise cleanup_failure
            handle.state = "committed"
            self._active.pop(id(handle), None)
        except BaseException as exc:
            diagnostics = await self._cleanup(handle, exc)
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                _attach_cleanup_diagnostics(exc, diagnostics)
                raise
            outward = RuntimeServiceError(
                phase="effect_commit", code="effect.commit_failed", safe_message="Effect 未被真实观察或结算失败"
            )
            if isinstance(exc, RuntimeServiceError) and exc.code == "effect.cleanup_failed":
                diagnostics = (*diagnostics, exc)
            _attach_cleanup_diagnostics(outward, diagnostics)
            raise outward from exc

    async def _finish(self, item: _PreparedEffect) -> object:
        if item.manager is not None:
            try:
                await item.manager.__aexit__(None, None, None)
            finally:
                item.manager_finished = True
            value = getattr(item.entered, "value", None)
            if value is None:
                value = getattr(item.manager, "value")
            return await _maybe_await(value)
        if item.event_future is None:
            raise RuntimeError("effect observer unavailable")
        return await item.event_future

    async def cleanup_active(
        self, error: BaseException | None = None
    ) -> tuple[RuntimeServiceError, ...]:
        diagnostics: list[RuntimeServiceError] = []
        for handle in tuple(self._active.values()):
            diagnostics.extend(await self._cleanup(handle, error))
        return tuple(diagnostics)

    async def _remove_listeners(
        self,
        handle: EffectHandle,
        *,
        suppress_control_flow: bool = False,
    ) -> tuple[RuntimeServiceError, ...]:
        diagnostics: list[RuntimeServiceError] = []
        for item in reversed(handle.prepared):
            for source, event_name, handler in reversed(item.listeners):
                remover = getattr(source, "remove_listener", None) or getattr(source, "off", None)
                if remover is not None:
                    try:
                        result = remover(event_name, handler)
                        if inspect.isawaitable(result):
                            await result
                    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                        if not suppress_control_flow:
                            raise
                        diagnostics.append(_cleanup_diagnostic())
                    except BaseException:
                        diagnostics.append(_cleanup_diagnostic())
            item.listeners.clear()
        return tuple(diagnostics)

    async def _cleanup(
        self, handle: EffectHandle, error: BaseException | None
    ) -> tuple[RuntimeServiceError, ...]:
        diagnostics: list[RuntimeServiceError] = []
        control_error: BaseException | None = None
        try:
            for item in reversed(handle.prepared):
                if item.event_future is not None and not item.event_future.done():
                    item.event_future.cancel()
                if item.manager is not None and not item.manager_finished:
                    try:
                        await item.manager.__aexit__(
                            type(error), error, getattr(error, "__traceback__", None)
                        )
                    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError) as exc:
                        if error is None and control_error is None:
                            control_error = exc
                        else:
                            diagnostics.append(_cleanup_diagnostic())
                    except BaseException:
                        diagnostics.append(_cleanup_diagnostic())
                    finally:
                        item.manager_finished = True
            diagnostics.extend(
                await self._remove_listeners(
                    handle,
                    suppress_control_flow=error is not None or control_error is not None,
                )
            )
        finally:
            handle.state = "cleaned"
            self._active.pop(id(handle), None)
        if control_error is not None:
            _attach_cleanup_diagnostics(control_error, tuple(diagnostics))
            raise control_error
        return tuple(diagnostics)


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python", exclude_none=True)
    raise RuntimeServiceError(
        phase="effect_prepare", code="effect.spec_invalid", safe_message="EffectSpec 格式无效"
    )


def _owning_page(scope: object) -> object:
    page = getattr(scope, "page", None)
    if page is None:
        return scope
    return page() if callable(page) else page


def _page_context(page: object) -> object:
    context = getattr(page, "context", None)
    if callable(context):
        context = context()
    if context is None:
        raise RuntimeError("page context unavailable")
    return context


async def _maybe_await(value: object) -> object:
    return await value if inspect.isawaitable(value) else value


def _cleanup_diagnostic() -> RuntimeServiceError:
    return RuntimeServiceError(
        phase="effect_commit",
        code="effect.cleanup_failed",
        safe_message="Effect 清理失败",
    )


def _attach_cleanup_diagnostics(
    error: BaseException,
    diagnostics: tuple[RuntimeServiceError, ...],
) -> None:
    if diagnostics and "effect.cleanup_failed" not in getattr(error, "__notes__", ()):
        error.add_note("effect.cleanup_failed")
