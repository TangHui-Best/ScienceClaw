from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import re
import sys
import traceback
from types import ModuleType

import pytest

from rpa_agent.compiler import DeterministicCompiler
from rpa_agent.contracts import SkillDefinition
from rpa_agent.runtime import (
    AgentExecutionError,
    DataAssetHandle,
    FrameResolutionError,
    InputValidationError,
    LocatorResolutionError,
    LocatorResolver,
    PageRegistryError,
    RunContext,
    RuntimeServiceError,
    StepExecutionError,
    VariableStoreError,
)


def run(awaitable):
    return asyncio.run(awaitable)


def definition(**overrides: object) -> SkillDefinition:
    payload = {
        "schema_version": "skill-definition/v0.1",
        "skill": {
            "id": "runtime-test",
            "name": "运行时测试",
            "version": "0.1.0",
            "description": "验证运行时边界",
        },
        "inputs": [
            {"ref": "query", "title": "查询", "value_type": "string", "required": True},
            {"ref": "limit", "title": "数量", "value_type": "number", "required": False, "default": 3},
            {"ref": "enabled", "title": "启用", "value_type": "boolean", "required": False, "default": False},
        ],
        "secrets": [{"ref": "erp.password", "title": "密码", "required": True}],
        "asset_inputs": [{"ref": "upload", "title": "上传文件", "required": False}],
        "outputs": [
            {"name": "order", "title": "订单", "variable_ref": "采购订单", "value_type": "json"}
        ],
        "asset_outputs": [{"name": "receipt_output", "title": "回执", "asset_ref": "receipt"}],
        "stage_2_rules": None,
    }
    payload.update(overrides)
    return SkillDefinition.model_validate(payload)


class FakeLocator:
    def __init__(
        self,
        count: int = 1,
        *,
        children: dict[tuple[str, str], "FakeLocator"] | None = None,
        frame: object | None = None,
        options: list[dict[str, str]] | None = None,
        filtered_count: int | None = None,
    ) -> None:
        self._count = count
        self._children = children or {}
        self.content_frame = frame
        self.options = options or []
        self.selected: list[dict[str, str]] = []
        self.waited: list[str] = []
        self.filtered_text: str | None = None
        self.filtered_count = filtered_count
        self.nth_calls: list[int] = []
        self.expect_states: list[bool] = []
        self.expect_observed: list[bool] = []

    async def count(self) -> int:
        return self._count

    def get_by_test_id(self, value: str) -> "FakeLocator":
        return self._children.get(("test_id", value), FakeLocator(0))

    def get_by_label(self, value: str, *, exact: bool = True) -> "FakeLocator":
        return self._children.get(("label", value), FakeLocator(0))

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = True) -> "FakeLocator":
        return self._children.get(("role", f"{role}:{name}"), FakeLocator(0))

    def locator(self, value: str) -> "FakeLocator":
        return self._children.get(("selector", value), FakeLocator(0))

    def filter(self, *, has_text: str) -> "FakeLocator":
        self.filtered_text = has_text
        if self.filtered_count is not None:
            self._count = self.filtered_count
        return self

    async def evaluate(self, script: str) -> list[dict[str, str]]:
        assert "option" in script
        return list(self.options)

    async def select_option(self, **kwargs: str) -> list[str]:
        self.selected.append(dict(kwargs))
        return [next(iter(kwargs.values()))]

    async def click(self) -> None:
        return None

    async def wait_for(self, *, state: str) -> None:
        self.waited.append(state)

    def nth(self, index: int) -> "FakeLocator":
        self.nth_calls.append(index)
        return FakeLocator(1)

    async def is_enabled(self) -> bool:
        return True


class FakeScope(FakeLocator):
    def __init__(self, mapping: dict[tuple[str, str], FakeLocator] | None = None) -> None:
        super().__init__(children=mapping)


class FakePage(FakeScope):
    def __init__(self, mapping: dict[tuple[str, str], FakeLocator] | None = None) -> None:
        super().__init__(mapping)
        self.closed = False
        self.url = "https://example.invalid/start"
        self.context: object | None = None
        self.goto_calls: list[str] = []
        self.navigation_event = FakeEventContext(self)
        self.download_event = FakeEventContext(None)
        self.listeners: dict[str, list[object]] = {}

    async def close(self) -> None:
        self.closed = True

    async def goto(self, value: str) -> None:
        self.goto_calls.append(value)
        self.url = value


    def expect_navigation(self) -> "FakeEventContext":
        return self.navigation_event

    def expect_download(self) -> "FakeEventContext":
        return self.download_event

    def on(self, event: str, handler: object) -> None:
        self.listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event: str, handler: object) -> None:
        self.listeners.get(event, []).remove(handler)

    def emit(self, event: str, value: object) -> None:
        for handler in tuple(self.listeners.get(event, [])):
            handler(value)


class FakeEventContext:
    def __init__(
        self,
        value: object,
        on_exit=None,
        *,
        enter_error: BaseException | None = None,
        exit_error: BaseException | None = None,
        value_error: BaseException | None = None,
    ) -> None:
        self._value = value
        self._on_exit = on_exit
        self._enter_error = enter_error
        self._exit_error = exit_error
        self._value_error = value_error
        self.entered = False
        self.exited = False
        self.exit_calls = 0

    async def __aenter__(self) -> "FakeEventContext":
        if self._enter_error is not None:
            raise self._enter_error
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exit_calls += 1
        self.exited = True
        if self._on_exit is not None and exc_type is None:
            self._on_exit()
        if self._exit_error is not None:
            raise self._exit_error

    @property
    async def value(self) -> object:
        if self._value_error is not None:
            raise self._value_error
        return self._value


class FakeDownload:
    suggested_filename = "receipt.csv"

    def __init__(self, path: str) -> None:
        self._path = path

    async def path(self) -> str:
        return self._path


class FakeBrowserContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.listeners: dict[str, list[object]] = {}
        self.remove_error: BaseException | None = None
        self.page_event = FakeEventContext(page, self._emit_page_and_download)

    def expect_page(self) -> FakeEventContext:
        return self.page_event

    def on(self, event: str, handler: object) -> None:
        self.listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event: str, handler: object) -> None:
        if self.remove_error is not None:
            raise self.remove_error
        self.listeners.get(event, []).remove(handler)

    def _emit_page_and_download(self) -> None:
        for handler in tuple(self.listeners.get("page", [])):
            handler(self.page)
        self.page.emit("download", self.page.download_event._value)


class FakeDialog:
    type = "prompt"

    def __init__(self) -> None:
        self.accepted: list[str | None] = []

    async def accept(self, value: str | None = None) -> None:
        self.accepted.append(value)

    async def dismiss(self) -> None:
        raise AssertionError("dialog should be accepted")


class SecretProvider:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    async def __call__(self, ref: str) -> str | None:
        return self.values.get(ref)

    def __repr__(self) -> str:
        return "SecretProvider(<hidden>)"


def make_context(
    *,
    page: FakePage | None = None,
    inputs: dict[str, object] | None = None,
    secrets: dict[str, str] | None = None,
    agent_backend=None,
    expect_factory=None,
) -> RunContext:
    return RunContext(
        run_id="run-1",
        definition=definition(),
        main_page=page or FakePage(),
        input_values={"query": "PO-001"} if inputs is None else inputs,
        secret_provider=SecretProvider(secrets or {"erp.password": "TOP-SECRET"}),
        asset_inputs={
            "upload": DataAssetHandle(ref="upload", runtime_value="opaque-upload", metadata={"name": "in.csv"})
        },
        agent_backend=agent_backend,
        expect_factory=expect_factory,
    )


def test_run_contexts_are_isolated_and_inputs_validate_required_type_and_defaults() -> None:
    left = make_context(inputs={"query": "A"})
    right = make_context(inputs={"query": "B", "limit": 5, "enabled": True})

    left.variables.write("采购订单.订单号", "PO-A")

    assert left.inputs.require("query") == "A"
    assert left.inputs.require("limit") == 3
    assert left.inputs.require("enabled") is False
    assert right.inputs.require("query") == "B"
    assert not right.variables.contains("采购订单")
    with pytest.raises(InputValidationError, match="input.required"):
        make_context(inputs={})
    with pytest.raises(InputValidationError, match="input.type"):
        make_context(inputs={"query": 123})
    with pytest.raises(InputValidationError, match="input.unknown"):
        make_context(inputs={"query": "A", "recorded-value": "must-not-fallback"})

    required_asset_definition = definition(
        asset_inputs=[{"ref": "upload", "title": "上传文件", "required": True}]
    )
    with pytest.raises(RuntimeServiceError, match="asset.required"):
        RunContext(
            run_id="missing-asset",
            definition=required_asset_definition,
            main_page=FakePage(),
            input_values={"query": "A"},
            secret_provider=SecretProvider({"erp.password": "x"}),
        )


def test_secret_is_async_required_and_never_appears_in_repr_or_result() -> None:
    ctx = make_context()

    assert run(ctx.secrets.require("erp.password")) == "TOP-SECRET"
    ctx.variables.write("采购订单", {"订单号": "PO-001"})
    result = ctx.results.succeeded(
        outputs=ctx.variables.export(("采购订单",)),
        data_assets=ctx.assets.export(("receipt",), allow_missing=True),
    )

    corpus = repr(ctx) + repr(ctx.secrets) + repr(result) + json.dumps(result.to_dict(), ensure_ascii=False)
    assert "TOP-SECRET" not in corpus
    with pytest.raises(RuntimeServiceError, match="secret.not_declared"):
        run(ctx.secrets.require("other"))
    isolated = make_context()
    secret = run(isolated.secrets.require("erp.password"))
    with pytest.raises(VariableStoreError, match="variable.secret_forbidden"):
        isolated.variables.write("采购订单", {"订单号": secret})
    with pytest.raises(ValueError, match="result.secret_forbidden"):
        isolated.results.succeeded(outputs={"order": secret}, data_assets={})


def test_secret_provider_failure_is_normalized_without_leaking_provider_exception() -> None:
    async def leaking_provider(ref: str) -> str | None:
        raise RuntimeError("provider failed with TOP-SECRET and raw vault payload")

    ctx = RunContext(
        run_id="secret-provider-failure",
        definition=definition(),
        main_page=FakePage(),
        input_values={"query": "PO-001"},
        secret_provider=leaking_provider,
        asset_inputs={"upload": DataAssetHandle("upload", "opaque")},
    )
    with pytest.raises(RuntimeServiceError) as caught:
        run(ctx.secrets.require("erp.password"))
    error = caught.value
    assert (error.phase, error.code) == ("input", "secret.provider_failed")
    rendered = "".join(traceback.format_exception(error)) + repr(error)
    assert "TOP-SECRET" not in rendered
    assert "raw vault" not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


def test_variable_store_supports_root_and_leaf_paths_and_rejects_conflicts() -> None:
    ctx = make_context()
    ctx.variables.write("采购订单.订单号", "PO-001")
    ctx.variables.write("采购订单.供应商", "供应商甲")

    assert ctx.variables.require("采购订单") == {"订单号": "PO-001", "供应商": "供应商甲"}
    assert ctx.variables.require("采购订单.订单号") == "PO-001"
    assert ctx.variables.contains("采购订单.供应商")
    with pytest.raises(VariableStoreError, match="variable.duplicate_write"):
        ctx.variables.write("采购订单.订单号", "PO-002")
    with pytest.raises(VariableStoreError, match="variable.path_conflict"):
        ctx.variables.write("采购订单.订单号.字符", "x")
    with pytest.raises(VariableStoreError, match="variable.output_not_declared"):
        ctx.variables.export(("采购订单.订单号",))
    assert ctx.variables.export(("采购订单",)) == {
        "order": {"订单号": "PO-001", "供应商": "供应商甲"}
    }

    separate = make_context()
    separate.variables.write("采购订单", {"订单号": "PO-001"})
    with pytest.raises(VariableStoreError, match="variable.path_conflict"):
        separate.variables.write("采购订单.供应商", "甲")


def test_variable_and_result_nested_values_are_recursively_isolated() -> None:
    ctx = make_context()
    source = {"订单号": "PO-001", "明细": [{"物料": "A"}]}
    ctx.variables.write("采购订单", source)
    source["明细"][0]["物料"] = "SOURCE-MUTATED"
    assert ctx.variables.require("采购订单.明细")[0]["物料"] == "A"

    required = ctx.variables.require("采购订单")
    required["明细"][0]["物料"] = "REQUIRE-MUTATED"
    assert ctx.variables.require("采购订单.明细")[0]["物料"] == "A"

    exported = ctx.variables.export(("采购订单",))
    exported["order"]["明细"][0]["物料"] = "EXPORT-MUTATED"
    assert ctx.variables.export(("采购订单",))["order"]["明细"][0]["物料"] == "A"

    result_source = ctx.variables.export(("采购订单",))
    result = ctx.results.succeeded(outputs=result_source, data_assets={})
    result_source["order"]["明细"][0]["物料"] = "RESULT-SOURCE-MUTATED"
    assert result.outputs["order"]["明细"][0]["物料"] == "A"
    with pytest.raises((TypeError, AttributeError)):
        result.outputs["order"]["明细"][0]["物料"] = "RESULT-MUTATED"

    first_payload = result.to_dict()
    first_payload["outputs"]["order"]["明细"][0]["物料"] = "DICT-MUTATED"
    assert result.to_dict()["outputs"]["order"]["明细"][0]["物料"] == "A"


def test_result_builder_rejects_undeclared_or_missing_exports() -> None:
    ctx = make_context()
    with pytest.raises(ValueError, match="result.output_not_declared"):
        ctx.results.succeeded(outputs={"中间变量": "x"}, data_assets={})
    with pytest.raises(ValueError, match="result.asset_not_declared"):
        ctx.results.succeeded(outputs={}, data_assets={"中间文件": {"ref": "中间文件"}})


def test_data_assets_export_safe_contract_without_absolute_path() -> None:
    ctx = make_context()
    runtime_path = str(Path.cwd().resolve() / "secret-local-download.csv")
    metadata = {"name": "receipt.csv"}
    ctx.assets.register(
        "receipt",
        DataAssetHandle(ref="receipt", runtime_value=runtime_path, metadata=metadata),
    )
    metadata["name"] = "MUTATED.csv"

    assert ctx.assets.require("receipt").runtime_value == runtime_path
    exported = ctx.assets.export(("receipt",))
    assert exported == {"receipt_output": {"ref": "receipt", "name": "receipt.csv"}}
    exported["receipt_output"]["name"] = "EXPORT-MUTATED.csv"
    assert ctx.assets.export(("receipt",))["receipt_output"]["name"] == "receipt.csv"
    assert runtime_path not in repr(exported)
    with pytest.raises(RuntimeServiceError, match="asset.duplicate"):
        ctx.assets.register("receipt", DataAssetHandle(ref="receipt", runtime_value="other"))


def test_page_registry_has_explicit_lifecycle_without_switch_creation_or_fallback() -> None:
    main = FakePage()
    popup = FakePage()
    ctx = make_context(page=main)

    assert ctx.pages.require("main") is main
    ctx.pages.register("popup", popup)
    assert ctx.pages.activate("popup") is popup
    with pytest.raises(PageRegistryError, match="page.unknown"):
        ctx.pages.activate("missing")
    assert ctx.pages.active_ref == "popup"
    run(ctx.pages.close("popup"))
    assert popup.closed
    assert ctx.pages.active_ref is None
    with pytest.raises(PageRegistryError, match="page.closed"):
        ctx.pages.require("popup")
    with pytest.raises(PageRegistryError, match="page.duplicate"):
        ctx.pages.register("main", FakePage())


def test_frame_resolver_walks_stable_locators_and_fails_closed() -> None:
    frame = FakeScope({("test_id", "inside"): FakeLocator(1)})
    iframe = FakeLocator(1, frame=frame)
    page = FakePage({("test_id", "acceptance-frame"): iframe})
    ctx = make_context(page=page)

    resolved = run(
        ctx.frames.resolve(
            page,
            [{"name": "验收表单", "locators": [{"strategy": "test_id", "value": "acceptance-frame"}]}],
        )
    )
    assert resolved is frame
    assert run(ctx.frames.resolve(page, [])) is page
    with pytest.raises(FrameResolutionError, match="frame.not_found"):
        run(ctx.frames.resolve(page, [{"name": "missing", "locators": [{"strategy": "test_id", "value": "none"}]}]))


def test_locator_auto_wait_allows_late_iframe_and_later_fallback_candidate() -> None:
    class AppearingLocator(FakeLocator):
        async def wait_for(self, *, state: str) -> None:
            assert state == "attached"
            await asyncio.sleep(0)
            self._count = 1

    class NeverLocator(FakeLocator):
        async def wait_for(self, *, state: str) -> None:
            assert state == "attached"
            await asyncio.Event().wait()

    frame = FakeScope()
    iframe = AppearingLocator(0, frame=frame)

    class TitleScope(FakePage):
        def get_by_title(self, value: str, *, exact: bool = True):
            return iframe if value == "验收登记表单" else FakeLocator(0)

    resolver = LocatorResolver(auto_wait_timeout_s=0.1)
    ctx = make_context(page=TitleScope())
    ctx.locators = resolver
    ctx.frames = type(ctx.frames)(resolver)
    resolved = run(
        ctx.frames.resolve(
            ctx.pages.require("main"),
            [{"name": "frame", "locators": [{"strategy": "title", "value": "验收登记表单"}]}],
        )
    )
    assert resolved is frame

    never = NeverLocator(0)
    later = AppearingLocator(0)
    scope = FakeScope({("test_id", "never"): never, ("test_id", "later"): later})
    selected = run(
        resolver.resolve(
            scope=scope,
            target={
                "name": "late fallback",
                "locators": [
                    {"strategy": "test_id", "value": "never"},
                    {"strategy": "test_id", "value": "later"},
                ],
            },
        )
    )
    assert selected is later


def test_locator_auto_wait_preserves_ambiguous_and_cancellation_semantics() -> None:
    class LateAmbiguous(FakeLocator):
        async def wait_for(self, *, state: str) -> None:
            self._count = 2

    class Cancelled(FakeLocator):
        async def wait_for(self, *, state: str) -> None:
            raise asyncio.CancelledError()

    resolver = LocatorResolver(auto_wait_timeout_s=0.1)
    with pytest.raises(LocatorResolutionError) as ambiguous:
        run(
            resolver.resolve(
                scope=FakeScope({("test_id", "many"): LateAmbiguous(0)}),
                target={"name": "many", "locators": [{"strategy": "test_id", "value": "many"}]},
            )
        )
    assert ambiguous.value.code == "locator.ambiguous"

    with pytest.raises(asyncio.CancelledError):
        run(
            resolver.resolve(
                scope=FakeScope({("test_id", "cancelled"): Cancelled(0)}),
                target={"name": "cancelled", "locators": [{"strategy": "test_id", "value": "cancelled"}]},
            )
        )


def test_locator_resolver_uses_candidate_order_and_never_silently_selects_ambiguous() -> None:
    unique = FakeLocator(1)
    ambiguous_candidate = FakeLocator(2)
    missing_candidate = FakeLocator(0)
    scope = FakeScope(
        {
            ("test_id", "none"): missing_candidate,
            ("label", "many"): ambiguous_candidate,
            ("role", "button:提交"): unique,
        }
    )
    ctx = make_context()
    target = {
        "name": "提交",
        "locators": [
            {"strategy": "test_id", "value": "none"},
            {"strategy": "label", "value": "many", "exact": True},
            {"strategy": "role", "role": "button", "name": "提交", "exact": True},
        ],
    }

    assert run(ctx.locators.resolve(scope=scope, target=target)) is unique
    assert unique.nth_calls == []
    assert ambiguous_candidate.nth_calls == []
    with pytest.raises(LocatorResolutionError) as error:
        run(ctx.locators.resolve(scope=scope, target={"name": "x", "locators": target["locators"][:2]}))
    assert error.value.code == "locator.ambiguous"
    with pytest.raises(LocatorResolutionError) as missing:
        run(ctx.locators.resolve(scope=scope, target={"name": "x", "locators": target["locators"][:1]}))
    assert missing.value.code == "locator.not_found"
    assert missing_candidate.nth_calls == []

    explicit = FakeLocator(2)
    indexed_scope = FakeScope({("test_id", "two"): explicit})
    selected = run(
        ctx.locators.resolve(
            scope=indexed_scope,
            target={
                "name": "explicit",
                "index": 1,
                "locators": [{"strategy": "test_id", "value": "two"}],
            },
        )
    )
    assert selected is not explicit
    assert explicit.nth_calls == [1]
    out_of_range = FakeLocator(2)
    with pytest.raises(LocatorResolutionError) as invalid_index:
        run(
            ctx.locators.resolve(
                scope=FakeScope({("test_id", "two"): out_of_range}),
                target={
                    "name": "explicit",
                    "index": 3,
                    "locators": [{"strategy": "test_id", "value": "two"}],
                },
            )
        )
    assert invalid_index.value.code == "locator.index_out_of_range"
    assert out_of_range.nth_calls == []


def test_locator_target_path_resolves_each_level_and_filter_binding_must_be_resolved() -> None:
    button = FakeLocator(1)
    row = FakeLocator(1, children={("role", "button:发起验收"): button})
    table = FakeScope({("role", "row:None"): row})
    ctx = make_context()
    target = {
        "name": "正确订单的发起验收",
        "path": [
            {
                "name": "订单行",
                "locators": [{"strategy": "role", "role": "row", "exact": True}],
                "filter_text": "PO-001",
            }
        ],
        "locators": [{"strategy": "role", "role": "button", "name": "发起验收", "exact": True}],
    }
    assert run(ctx.locators.resolve(scope=table, target=target)) is button
    assert row.filtered_text == "PO-001"
    target["path"][0].pop("filter_text")
    target["path"][0]["filter_binding"] = "order"
    with pytest.raises(LocatorResolutionError, match="locator.filter_binding_unresolved"):
        run(ctx.locators.resolve(scope=table, target=target))

    narrowed_button = FakeLocator(1)
    many_rows = FakeLocator(
        2,
        filtered_count=1,
        children={("role", "button:发起验收"): narrowed_button},
    )
    multi_table = FakeScope({("role", "row:None"): many_rows})
    target["path"][0].pop("filter_binding")
    target["path"][0]["filter_text"] = "PO-001"
    assert run(ctx.locators.resolve(scope=multi_table, target=target)) is narrowed_button


def test_select_option_preflights_value_then_label_and_never_retries_page_errors() -> None:
    value_target = FakeLocator(options=[{"value": "pending", "label": "待验收"}])
    label_target = FakeLocator(options=[{"value": "P", "label": "待验收"}])
    ctx = make_context()

    run(ctx.steps.select_option(target=value_target, option="pending"))
    run(ctx.steps.select_option(target=label_target, option="待验收"))
    assert value_target.selected == [{"value": "pending"}]
    assert label_target.selected == [{"label": "待验收"}]
    with pytest.raises(RuntimeServiceError) as not_found:
        run(ctx.steps.select_option(target=FakeLocator(options=[]), option="missing"))
    assert (not_found.value.phase, not_found.value.code) == ("input", "select.option_not_found")

    class Crashed(FakeLocator):
        async def evaluate(self, script: str):
            raise RuntimeError("browser crashed with internal detail")

    with pytest.raises(RuntimeServiceError) as crashed:
        run(ctx.steps.select_option(target=Crashed(), option="x"))
    assert crashed.value.code == "select.inspect_failed"
    assert "internal detail" not in crashed.value.safe_message

    class Cancelled(FakeLocator):
        async def evaluate(self, script: str):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        run(ctx.steps.select_option(target=Cancelled(), option="x"))


def test_step_executor_wraps_identity_phase_and_stops_after_first_failure() -> None:
    ctx = make_context()
    calls: list[str] = []

    async def broken() -> None:
        calls.append("broken")
        raise RuntimeError("DOM dump and secret TOP-SECRET")

    with pytest.raises(StepExecutionError) as caught:
        run(ctx.steps.execute(trace_id="trace-1", sequence=10, action_kind="click", operation=broken))
    assert calls == ["broken"]
    assert (caught.value.run_id, caught.value.trace_id, caught.value.sequence) == ("run-1", "trace-1", 10)
    assert (caught.value.phase, caught.value.code) == ("action", "action.failed")
    assert "TOP-SECRET" not in str(caught.value)


def test_step_executor_preserves_service_phase_and_code() -> None:
    async def capture(operation, *, trace_id: str) -> StepExecutionError:
        ctx = make_context()
        with pytest.raises(StepExecutionError) as caught:
            await ctx.steps.execute(
                trace_id=trace_id,
                sequence=10,
                action_kind="fill",
                operation=lambda: operation(ctx),
            )
        return caught.value

    async def missing_page(ctx: RunContext) -> None:
        ctx.pages.require("missing")

    async def missing_variable(ctx: RunContext) -> None:
        ctx.variables.require("采购订单.订单号")

    async def duplicate_output(ctx: RunContext) -> None:
        ctx.variables.write("采购订单", {})
        ctx.variables.write("采购订单", {})

    page_error = run(capture(missing_page, trace_id="scope"))
    input_error = run(capture(missing_variable, trace_id="input"))
    output_error = run(capture(duplicate_output, trace_id="output"))
    assert (page_error.phase, page_error.code) == ("scope", "page.unknown")
    assert (input_error.phase, input_error.code) == ("input", "variable.missing")
    assert (output_error.phase, output_error.code) == ("output", "variable.duplicate_write")


def test_agent_executor_enforces_declared_outputs_and_required_leaf_paths() -> None:
    captured: dict[str, object] = {}

    async def backend(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"order": {"订单号": "PO-001", "供应商": "甲"}}

    ctx = make_context(agent_backend=backend)
    outputs = run(
        ctx.agent.execute(
            scope=object(),
            target=None,
            instruction="提取订单",
            inputs={"query": "PO-001"},
            output_names=("order",),
            required_paths={"order": ("订单号", "供应商")},
        )
    )
    assert outputs["order"]["订单号"] == "PO-001"
    assert set(captured) == {
        "scope", "target", "instruction", "inputs", "output_names", "required_paths",
        "variables", "sensitive_data", "data_assets", "step_id", "scope_hint",
        "expected_effects", "model_policy", "asset_output_refs",
    }

    async def undeclared(**kwargs: object) -> dict[str, object]:
        return {"order": {}, "secret": "leak"}

    ctx = make_context(agent_backend=undeclared)
    with pytest.raises(AgentExecutionError, match="agent.output_undeclared"):
        run(ctx.agent.execute(scope=object(), target=None, instruction="x", inputs={}, output_names=("order",), required_paths={}))

    async def missing_leaf(**kwargs: object) -> dict[str, object]:
        return {"order": {"订单号": "PO-001"}}

    ctx = make_context(agent_backend=missing_leaf)
    with pytest.raises(AgentExecutionError, match="agent.required_path_missing"):
        run(ctx.agent.execute(scope=object(), target=None, instruction="x", inputs={}, output_names=("order",), required_paths={"order": ("供应商",)}))

    secret = run(ctx.secrets.require("erp.password"))
    with pytest.raises(AgentExecutionError, match="agent.secret_input_forbidden"):
        run(ctx.agent.execute(scope=object(), target=None, instruction="x", inputs={"password": secret}, output_names=("order",), required_paths={}))

    async def crashing(**kwargs: object) -> dict[str, object]:
        raise RuntimeError("TOP-SECRET plus DOM dump")

    ctx = make_context(agent_backend=crashing)
    with pytest.raises(AgentExecutionError) as safe_failure:
        run(ctx.agent.execute(scope=object(), target=None, instruction="x", inputs={}, output_names=("order",), required_paths={}))
    assert safe_failure.value.code == "agent.execution_failed"
    assert "TOP-SECRET" not in str(safe_failure.value)


class FakeExpectAssertion:
    def __init__(self, subject: object, calls: list[tuple[str, object]], *, fail: bool = False) -> None:
        self.subject = subject
        self.calls = calls
        self.fail = fail

    async def _record(self, name: str, value: object = None) -> None:
        self.calls.append((name, value))
        if self.fail:
            raise AssertionError("playwright timeout with DOM detail")

    async def to_be_enabled(self) -> None:
        while getattr(self.subject, "expect_states", []):
            self.subject.expect_observed.append(self.subject.expect_states.pop(0))
        if getattr(self.subject, "expect_observed", []) and not self.subject.expect_observed[-1]:
            raise AssertionError("expect deadline reached")
        await self._record("to_be_enabled")

    async def to_be_disabled(self) -> None:
        await self._record("to_be_disabled")

    async def to_be_checked(self, *, checked: bool = True) -> None:
        await self._record("to_be_checked", checked)

    async def to_have_text(self, expected: object) -> None:
        await self._record("to_have_text", expected)

    async def to_contain_text(self, expected: object) -> None:
        await self._record("to_contain_text", expected)

    async def to_have_value(self, expected: object) -> None:
        await self._record("to_have_value", expected)

    async def to_have_url(self, expected: object) -> None:
        await self._record("to_have_url", expected)


def fake_expect_factory(calls: list[tuple[str, object]], *, fail: bool = False):
    return lambda subject: FakeExpectAssertion(subject, calls, fail=fail)


def test_wait_executor_uses_playwright_waiting_assertions_without_manual_polling() -> None:
    target = FakeLocator(1)
    target.expect_states = [False, True]
    scope = FakeScope({("test_id", "ready"): target})
    calls: list[tuple[str, object]] = []
    ctx = make_context(expect_factory=fake_expect_factory(calls))
    run(
        ctx.waits.until(
            scope=scope,
            conditions=[
                {
                    "kind": "element_state",
                    "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]},
                    "state": "visible",
                }
            ],
        )
    )
    assert target.waited == ["visible"]
    run(
        ctx.waits.until(
            scope=scope,
            conditions=[
                {
                    "kind": "element_state",
                    "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]},
                    "state": "enabled",
                }
            ],
        )
    )
    conditions = [
        {"kind": "element_state", "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]}, "state": "disabled"},
        {"kind": "element_state", "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]}, "state": "checked"},
        {"kind": "element_state", "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]}, "state": "unchecked"},
        {"kind": "element_text", "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]}, "operator": "contains", "expected": "完成"},
        {"kind": "element_value", "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]}, "operator": "regex", "expected": "^PO-[0-9]+$"},
        {"kind": "url_matches", "operator": "exact", "expected": "https://example.invalid/start"},
    ]
    run(ctx.waits.until(scope=scope, conditions=conditions))
    assert [name for name, _ in calls] == [
        "to_be_enabled", "to_be_disabled", "to_be_checked", "to_be_checked",
        "to_contain_text", "to_have_value", "to_have_url",
    ]
    assert calls[3] == ("to_be_checked", False)
    assert isinstance(calls[5][1], re.Pattern)
    assert target.expect_observed == [False, True]
    with pytest.raises(RuntimeServiceError, match="wait.conditions_required"):
        run(ctx.waits.until(scope=scope, conditions=[]))


def test_wait_executor_normalizes_target_timeout_regex_and_cancellation() -> None:
    target = FakeLocator(1)
    scope = FakeScope({("test_id", "ready"): target})
    timeout_ctx = make_context(expect_factory=fake_expect_factory([], fail=True))
    with pytest.raises(RuntimeServiceError) as timeout:
        run(timeout_ctx.waits.until(scope=scope, conditions=[
            {"kind": "element_state", "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]}, "state": "enabled"}
        ]))
    assert (timeout.value.phase, timeout.value.code) == ("wait", "wait.condition_failed")
    assert "DOM detail" not in timeout.value.safe_message

    ctx = make_context(expect_factory=fake_expect_factory([]))
    with pytest.raises(RuntimeServiceError) as missing:
        run(ctx.waits.until(scope=scope, conditions=[
            {"kind": "element_text", "target": {"name": "missing", "locators": [{"strategy": "test_id", "value": "none"}]}, "operator": "exact", "expected": "x"}
        ]))
    assert (missing.value.phase, missing.value.code) == ("wait", "wait.target_resolution_failed")
    with pytest.raises(RuntimeServiceError) as invalid_regex:
        run(ctx.waits.until(scope=scope, conditions=[
            {"kind": "element_value", "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]}, "operator": "regex", "expected": "["}
        ]))
    assert (invalid_regex.value.phase, invalid_regex.value.code) == ("wait", "wait.regex_invalid")

    class CancelExpect(FakeExpectAssertion):
        async def to_be_enabled(self) -> None:
            raise asyncio.CancelledError()

    cancelled_ctx = make_context(expect_factory=lambda subject: CancelExpect(subject, []))
    with pytest.raises(asyncio.CancelledError):
        run(cancelled_ctx.waits.until(scope=scope, conditions=[
            {"kind": "element_state", "target": {"name": "ready", "locators": [{"strategy": "test_id", "value": "ready"}]}, "state": "enabled"}
        ]))


def test_wait_failure_through_step_is_wait_phase_and_select_cancel_cleans_effect() -> None:
    async def scenario() -> None:
        page = FakePage({("test_id", "none"): FakeLocator(0)})
        ctx = make_context(page=page, expect_factory=fake_expect_factory([]))

        async def wait_failure() -> None:
            await ctx.waits.until(scope=page, conditions=[
                {"kind": "element_text", "target": {"name": "missing", "locators": [{"strategy": "test_id", "value": "none"}]}, "operator": "exact", "expected": "x"}
            ])

        with pytest.raises(StepExecutionError) as failed:
            await ctx.steps.execute(
                trace_id="wait-failure",
                sequence=40,
                action_kind="click",
                operation=wait_failure,
            )
        assert (failed.value.phase, failed.value.code) == (
            "wait", "wait.target_resolution_failed"
        )

        class CancelledSelect(FakeLocator):
            async def evaluate(self, script: str):
                raise asyncio.CancelledError()

        async def cancelled_select() -> None:
            await ctx.effects.prepare(scope=page, effects=[{"kind": "navigation"}])
            await ctx.steps.select_option(target=CancelledSelect(), option="x")

        with pytest.raises(asyncio.CancelledError):
            await ctx.steps.execute(
                trace_id="select-cancelled",
                sequence=50,
                action_kind="select",
                operation=cancelled_select,
            )
        assert page.navigation_event.exited

    run(scenario())


def test_effects_are_installed_before_action_committed_truthfully_and_cleaned_on_failure() -> None:
    main = FakePage()
    popup = FakePage()
    popup.download_event = FakeEventContext(FakeDownload(str(Path.cwd() / "receipt.csv")))
    main.context = FakeBrowserContext(popup)
    ctx = make_context(page=main)

    handle = run(
        ctx.effects.prepare(
            scope=main,
            effects=[
                {"kind": "new_page", "page_ref": "popup"},
                {"kind": "download", "binding": "download", "asset_ref": "receipt"},
            ],
        )
    )
    assert main.context.page_event.entered
    assert "page" in main.context.listeners
    assert not main.download_event.entered
    run(ctx.effects.commit(handle))
    assert ctx.pages.require("popup") is popup
    assert ctx.assets.require("receipt").public_contract()["name"] == "receipt.csv"
    assert not main.context.listeners["page"]
    assert not popup.listeners["download"]

    second = FakePage()
    second.navigation_event = FakeEventContext(second)
    ctx = make_context(page=second)

    async def failed_action() -> None:
        await ctx.effects.prepare(scope=second, effects=[{"kind": "navigation"}])
        raise RuntimeError("failure after listener installation")

    with pytest.raises(StepExecutionError):
        run(ctx.steps.execute(trace_id="effect-fail", sequence=20, action_kind="click", operation=failed_action))
    assert second.navigation_event.exited


def test_effect_coordinator_rejects_unobserved_or_unsupported_effects() -> None:
    ctx = make_context()
    with pytest.raises(RuntimeServiceError) as unsupported:
        run(ctx.effects.prepare(scope=ctx.pages.require("main"), effects=[{"kind": "made_up"}]))
    assert (unsupported.value.phase, unsupported.value.code) == ("effect_prepare", "effect.unsupported")

    empty = run(ctx.effects.prepare(scope=ctx.pages.require("main"), effects=[]))
    run(ctx.effects.commit(empty))


def test_effect_cleanup_never_masks_operation_or_cancellation_and_keeps_safe_diagnostic() -> None:
    class OperationFailed(RuntimeError):
        pass

    async def scenario(error: BaseException) -> BaseException:
        page = FakePage()
        page.navigation_event = FakeEventContext(
            page,
            exit_error=RuntimeError("cleanup failed with TOP-SECRET"),
        )
        ctx = make_context(page=page)

        async def operation() -> None:
            await ctx.effects.prepare(scope=page, effects=[{"kind": "navigation"}])
            raise error

        expected_type = asyncio.CancelledError if isinstance(error, asyncio.CancelledError) else StepExecutionError
        with pytest.raises(expected_type) as caught:
            await ctx.steps.execute(
                trace_id="cleanup-priority",
                sequence=60,
                action_kind="click",
                operation=operation,
            )
        assert page.navigation_event.exit_calls == 1
        return caught.value

    original = OperationFailed("original operation failure")
    normal = run(scenario(original))
    assert normal.__cause__ is original
    assert getattr(normal, "__notes__", []) == ["effect.cleanup_failed"]
    assert "TOP-SECRET" not in repr(normal.__notes__)

    cancellation = asyncio.CancelledError()
    cancelled = run(scenario(cancellation))
    assert cancelled is cancellation
    assert getattr(cancelled, "__notes__", []) == ["effect.cleanup_failed"]


def test_effect_prepare_and_commit_keep_primary_failure_and_never_double_finish_manager() -> None:
    async def scenario() -> None:
        popup = FakePage()
        page = FakePage()
        context = FakeBrowserContext(popup)
        enter_error = RuntimeError("primary enter failure")
        context.page_event = FakeEventContext(popup, enter_error=enter_error)
        context.remove_error = RuntimeError("cleanup listener failure TOP-SECRET")
        page.context = context
        ctx = make_context(page=page)
        with pytest.raises(RuntimeServiceError) as prepare_failed:
            await ctx.effects.prepare(
                scope=page,
                effects=[
                    {"kind": "new_page", "page_ref": "popup"},
                    {"kind": "download", "binding": "download", "asset_ref": "receipt"},
                ],
            )
        assert prepare_failed.value.code == "effect.prepare_failed"
        assert prepare_failed.value.__cause__ is enter_error
        assert getattr(prepare_failed.value, "__notes__", []) == ["effect.cleanup_failed"]
        assert "TOP-SECRET" not in repr(prepare_failed.value.__notes__)

        commit_page = FakePage()
        value_error = RuntimeError("primary value failure")
        commit_page.navigation_event = FakeEventContext(commit_page, value_error=value_error)
        commit_ctx = make_context(page=commit_page)
        handle = await commit_ctx.effects.prepare(
            scope=commit_page, effects=[{"kind": "navigation"}]
        )
        with pytest.raises(RuntimeServiceError) as commit_failed:
            await commit_ctx.effects.commit(handle)
        assert commit_failed.value.code == "effect.commit_failed"
        assert commit_failed.value.__cause__ is value_error
        assert commit_page.navigation_event.exit_calls == 1

    run(scenario())


def test_effect_normal_commit_cleanup_preserves_new_cancellation_control_flow() -> None:
    async def scenario() -> None:
        popup = FakePage()
        popup.download_event = FakeEventContext(FakeDownload(str(Path.cwd() / "receipt.csv")))
        page = FakePage()
        context = FakeBrowserContext(popup)
        cancellation = asyncio.CancelledError()
        context.remove_error = cancellation
        page.context = context
        ctx = make_context(page=page)
        handle = await ctx.effects.prepare(
            scope=page,
            effects=[
                {"kind": "new_page", "page_ref": "popup"},
                {"kind": "download", "binding": "download", "asset_ref": "receipt"},
            ],
        )
        with pytest.raises(asyncio.CancelledError) as caught:
            await ctx.effects.commit(handle)
        assert caught.value is cancellation
        assert context.page_event.exit_calls == 1

    run(scenario())


def test_dialog_effect_is_temporary_and_cancellation_cleans_listener() -> None:
    async def scenario() -> None:
        page = FakePage()
        ctx = make_context(page=page)
        dialog = FakeDialog()
        handle = await ctx.effects.prepare(
            scope=page,
            effects=[
                {
                    "kind": "dialog",
                    "dialog_type": "prompt",
                    "response": "accept",
                    "input_value": "确认",
                }
            ],
        )
        assert page.listeners["dialog"]
        page.emit("dialog", dialog)
        await ctx.effects.commit(handle)
        assert dialog.accepted == ["确认"]
        assert not page.listeners["dialog"]

        async def cancelled() -> None:
            await ctx.effects.prepare(scope=page, effects=[{"kind": "navigation"}])
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await ctx.steps.execute(
                trace_id="cancelled",
                sequence=30,
                action_kind="click",
                operation=cancelled,
            )
        assert page.navigation_event.exited

    run(scenario())


@pytest.mark.parametrize("response", ["accept", "dismiss"])
def test_dialog_handler_cancellation_terminates_commit_without_callback_error(response: str) -> None:
    async def scenario() -> None:
        page = FakePage()
        ctx = make_context(page=page)
        cancellation = asyncio.CancelledError()
        loop_errors: list[dict[str, object]] = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(dict(context)))

        class CancelledDialog:
            type = "prompt"

            async def accept(self, value: str | None = None) -> None:
                raise cancellation

            async def dismiss(self) -> None:
                raise cancellation

        try:
            handle = await ctx.effects.prepare(
                scope=page,
                effects=[
                    {
                        "kind": "dialog",
                        "dialog_type": "prompt",
                        "response": response,
                        **({"input_value": "确认"} if response == "accept" else {}),
                    }
                ],
            )
            page.emit("dialog", CancelledDialog())
            with pytest.raises(asyncio.CancelledError) as caught:
                await asyncio.wait_for(ctx.effects.commit(handle), timeout=0.2)
            assert caught.value is cancellation
            assert not page.listeners["dialog"]
        finally:
            loop.set_exception_handler(previous_handler)
        assert loop_errors == []

    run(scenario())


def test_dialog_handler_failure_is_bounded_and_safely_normalized() -> None:
    async def scenario() -> None:
        page = FakePage()
        ctx = make_context(page=page)
        loop_errors: list[dict[str, object]] = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(dict(context)))

        class FailedDialog:
            type = "prompt"

            async def accept(self, value: str | None = None) -> None:
                raise RuntimeError("dialog failure with TOP-SECRET and raw DOM")

        try:
            handle = await ctx.effects.prepare(
                scope=page,
                effects=[
                    {
                        "kind": "dialog",
                        "dialog_type": "prompt",
                        "response": "accept",
                        "input_value": "确认",
                    }
                ],
            )
            page.emit("dialog", FailedDialog())
            with pytest.raises(RuntimeServiceError) as caught:
                await asyncio.wait_for(ctx.effects.commit(handle), timeout=0.2)
            rendered = "".join(traceback.format_exception(caught.value))
            assert caught.value.code == "effect.commit_failed"
            assert "TOP-SECRET" not in rendered
            assert "raw DOM" not in rendered
        finally:
            loop.set_exception_handler(previous_handler)
        assert loop_errors == []

    run(scenario())


def test_generated_four_file_skill_imports_and_minimal_segment_runs(tmp_path: Path) -> None:
    timeline = {
        "schema_version": "core-trace/v0.1",
        "traces": [
            {
                "trace_id": "trace_agent",
                "sequence": 10,
                "scope": {"page_ref": "main", "frame_path": []},
                "action": {"kind": "agent", "instruction": "提取当前订单"},
                "data_bindings": [
                    {
                        "name": "order",
                        "direction": "output",
                        "kind": "variable",
                        "ref": "采购订单",
                        "sensitive": False,
                    }
                ],
                "effects": [],
            },
            {
                "trace_id": "trace_popup",
                "sequence": 20,
                "scope": {"page_ref": "main", "frame_path": []},
                "action": {
                    "kind": "click",
                    "target": {"name": "发起验收", "locators": [{"strategy": "test_id", "value": "open"}]},
                },
                "data_bindings": [],
                "effects": [{"kind": "new_page", "page_ref": "popup"}],
            },
            {
                "trace_id": "trace_select",
                "sequence": 30,
                "scope": {
                    "page_ref": "popup",
                    "frame_path": [
                        {
                            "name": "验收iframe",
                            "locators": [{"strategy": "test_id", "value": "acceptance-frame"}],
                        }
                    ],
                },
                "action": {
                    "kind": "select",
                    "target": {"name": "状态", "locators": [{"strategy": "test_id", "value": "status"}]},
                },
                "data_bindings": [{"name": "option", "direction": "input", "kind": "literal", "value": "pending", "sensitive": False}],
                "effects": [],
            }
        ],
    }
    skill_definition = definition(inputs=[], secrets=[], asset_inputs=[], asset_outputs=[])
    destination = tmp_path / "generated_skill"
    compiled = DeterministicCompiler().compile(timeline, skill_definition, destination)
    assert compiled.status == "published", compiled.issues
    assert sorted(path.name for path in destination.iterdir()) == [
        "SKILL.md", "browser_segment.py", "skill.manifest.json", "skill.py"
    ]

    package = ModuleType("generated_skill")
    package.__path__ = [str(destination)]  # type: ignore[attr-defined]
    sys.modules["generated_skill"] = package
    try:
        for module_name in ("browser_segment", "skill"):
            spec = importlib.util.spec_from_file_location(
                f"generated_skill.{module_name}", destination / f"{module_name}.py"
            )
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        target = FakeLocator(options=[{"value": "pending", "label": "待验收"}])
        frame = FakeScope({("test_id", "status"): target})
        popup = FakePage({("test_id", "acceptance-frame"): FakeLocator(frame=frame)})
        page = FakePage({("test_id", "open"): FakeLocator()})
        page.context = FakeBrowserContext(popup)

        async def generated_agent(**kwargs: object) -> dict[str, object]:
            return {"order": {"订单号": "PO-001"}}

        ctx = RunContext(
            run_id="generated-run",
            definition=skill_definition,
            main_page=page,
            input_values={},
            secret_provider=SecretProvider({}),
            agent_backend=generated_agent,
        )
        result = run(sys.modules["generated_skill.skill"].execute_skill(ctx))
    finally:
        for name in ("generated_skill.skill", "generated_skill.browser_segment", "generated_skill"):
            sys.modules.pop(name, None)

    assert result.status == "succeeded"
    assert target.selected == [{"value": "pending"}]
    assert result.outputs == {"order": {"订单号": "PO-001"}}
    assert [step.trace_id for step in result.steps] == ["trace_agent", "trace_popup", "trace_select"]
