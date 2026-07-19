from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from rpa_agent.runtime import RunContext


ACCEPTANCE_FRAME_PATH = [
    {
        "name": "验收登记表单 iframe",
        "locators": [
            {"strategy": "title", "value": "验收登记表单", "exact": True},
            {"strategy": "css", "value": 'iframe[name="acceptance-form"]'},
        ],
    }
]


async def _scope(
    ctx: RunContext,
    page_ref: str,
    frame_path: list[dict[str, Any]] | None = None,
) -> Any:
    page = ctx.pages.require(page_ref)
    return await ctx.frames.resolve(page, frame_path or [])


async def _target(
    ctx: RunContext,
    scope: Any,
    *,
    name: str,
    locators: list[dict[str, Any]],
    path: list[dict[str, Any]] | None = None,
) -> Any:
    return await ctx.locators.resolve(
        scope=scope,
        name=name,
        path=path or [],
        locators=locators,
    )


async def _run_step(
    ctx: RunContext,
    *,
    trace_id: str,
    sequence: int,
    action_kind: str,
    label: str,
    operation: Callable[[], Awaitable[None]],
) -> None:
    await ctx.steps.execute(
        trace_id=trace_id,
        sequence=sequence,
        action_kind=action_kind,
        label=label,
        operation=operation,
    )


async def step_010_navigate(ctx: RunContext) -> None:
    """打开系统 A 的采购订单查询页。"""
    page = ctx.pages.require("main")
    await page.goto(str(ctx.inputs.require("system_a_url")))
    form = await _target(
        ctx,
        page,
        name="采购订单综合查询区",
        locators=[
            {"strategy": "test_id", "value": "order-query-form"},
            {
                "strategy": "role",
                "role": "form",
                "name": "采购订单综合查询",
                "exact": True,
            },
        ],
    )
    await form.wait_for(state="visible")


async def step_020_click(ctx: RunContext) -> None:
    """展开业务类型自定义下拉框。"""
    scope = await _scope(ctx, "main")
    target = await _target(
        ctx,
        scope,
        name="业务类型下拉框",
        locators=[
            {
                "strategy": "role",
                "role": "combobox",
                "name": "业务类型",
                "exact": True,
            },
            {"strategy": "test_id", "value": "business-type-combobox"},
        ],
    )
    await target.click()


async def step_030_click(ctx: RunContext) -> None:
    """按本次 Skill Input 选择业务类型，不使用录制值。"""
    scope = await _scope(ctx, "main")
    option = str(ctx.inputs.require("query.business_type"))
    target = await _target(
        ctx,
        scope,
        name="与 Skill Input 匹配的业务类型选项",
        path=[
            {
                "name": "业务类型选项列表",
                "locators": [
                    {
                        "strategy": "role",
                        "role": "listbox",
                        "name": "业务类型选项",
                        "exact": True,
                    },
                    {"strategy": "test_id", "value": "business-type-options"},
                ],
            },
            {
                "name": "业务类型匹配项",
                "locators": [{"strategy": "role", "role": "option"}],
                "filter_text": option,
            },
        ],
        locators=[{"strategy": "css", "value": '[data-testid="option-label"]'}],
    )
    await target.click()


async def step_040_fill(ctx: RunContext) -> None:
    """填写订单日期起始日。"""
    scope = await _scope(ctx, "main")
    target = await _target(
        ctx,
        scope,
        name="订单日期起始日",
        locators=[
            {"strategy": "label", "value": "订单日期起始日", "exact": True},
            {"strategy": "test_id", "value": "order-date-from"},
        ],
    )
    await target.fill(str(ctx.inputs.require("query.date_from")))


async def step_050_fill(ctx: RunContext) -> None:
    """填写订单日期结束日。"""
    scope = await _scope(ctx, "main")
    target = await _target(
        ctx,
        scope,
        name="订单日期结束日",
        locators=[
            {"strategy": "label", "value": "订单日期结束日", "exact": True},
            {"strategy": "test_id", "value": "order-date-to"},
        ],
    )
    await target.fill(str(ctx.inputs.require("query.date_to")))


async def step_060_fill(ctx: RunContext) -> None:
    """填写供应商查询条件。"""
    scope = await _scope(ctx, "main")
    target = await _target(
        ctx,
        scope,
        name="供应商名称查询框",
        locators=[
            {"strategy": "label", "value": "供应商名称", "exact": True},
            {"strategy": "placeholder", "value": "请输入供应商名称", "exact": True},
        ],
    )
    await target.fill(str(ctx.inputs.require("query.supplier_name")))


async def step_070_fill(ctx: RunContext) -> None:
    """填写订单编号查询条件。"""
    scope = await _scope(ctx, "main")
    target = await _target(
        ctx,
        scope,
        name="订单编号查询框",
        locators=[
            {"strategy": "label", "value": "订单编号", "exact": True},
            {"strategy": "placeholder", "value": "请输入订单编号", "exact": True},
        ],
    )
    await target.fill(str(ctx.inputs.require("query.order_no")))


async def step_080_click(ctx: RunContext) -> None:
    """点击只有图标、但具有查询语义的按钮。"""
    scope = await _scope(ctx, "main")
    target = await _target(
        ctx,
        scope,
        name="图标查询按钮",
        locators=[
            {"strategy": "role", "role": "button", "name": "查询", "exact": True},
            {"strategy": "test_id", "value": "query-orders"},
        ],
    )
    await target.click()
    table = await _target(
        ctx,
        scope,
        name="采购订单查询结果表格",
        locators=[
            {"strategy": "test_id", "value": "order-results-table"},
            {
                "strategy": "role",
                "role": "table",
                "name": "采购订单查询结果",
                "exact": True,
            },
        ],
    )
    await table.wait_for(state="visible")


async def step_090_agent(ctx: RunContext) -> None:
    """受控 Agent 提取采购订单根对象；这是本 Skill 唯一的运行时 LLM Call。"""
    scope = await _scope(ctx, "main")
    table = await _target(
        ctx,
        scope,
        name="采购订单查询结果表格",
        locators=[
            {"strategy": "test_id", "value": "order-results-table"},
            {
                "strategy": "role",
                "role": "table",
                "name": "采购订单查询结果",
                "exact": True,
            },
        ],
    )
    outputs = await ctx.agent.execute(
        scope=scope,
        target=table,
        instruction=(
            "在采购订单查询结果表格中找到订单编号等于输入 order_no 的唯一一行，"
            "提取订单号、供应商、合同号、含税金额、币种和订单日期，并以 result 对象返回。"
            "字段名必须分别为：订单号、供应商、合同号、含税金额、币种、订单日期。"
        ),
        inputs={"order_no": ctx.inputs.require("query.order_no")},
        output_names=("result",),
    )
    ctx.variables.write("采购订单", outputs["result"])


async def step_100_click(ctx: RunContext) -> None:
    """在目标订单行点击同名按钮，并在点击前监听新 Page。"""
    page = ctx.pages.require("main")
    row_key = str(ctx.inputs.require("query.order_no"))
    target = await _target(
        ctx,
        page,
        name="目标采购订单行的发起验收按钮",
        path=[
            {
                "name": "采购订单查询结果表格",
                "locators": [
                    {"strategy": "test_id", "value": "order-results-table"},
                    {
                        "strategy": "role",
                        "role": "table",
                        "name": "采购订单查询结果",
                        "exact": True,
                    },
                ],
            },
            {
                "name": "订单号匹配的目标行",
                "locators": [{"strategy": "role", "role": "row"}],
                "filter_text": row_key,
            },
        ],
        locators=[
            {
                "strategy": "role",
                "role": "button",
                "name": "发起验收",
                "exact": True,
            }
        ],
    )
    async with ctx.effects.capture_new_page(
        source_page=page,
        page_ref="acceptance_detail",
    ):
        await target.click()

    new_page = ctx.pages.require("acceptance_detail")
    heading = await _target(
        ctx,
        new_page,
        name="采购订单验收登记标题",
        locators=[
            {
                "strategy": "role",
                "role": "heading",
                "name": "采购订单验收登记",
                "exact": True,
            },
            {"strategy": "test_id", "value": "acceptance-page-title"},
        ],
    )
    await heading.wait_for(state="visible")


async def step_110_fill(ctx: RunContext) -> None:
    """在 iframe 内填写来源订单号。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="来源订单号",
        locators=[
            {"strategy": "label", "value": "来源订单号", "exact": True},
            {"strategy": "test_id", "value": "source-order-no"},
        ],
    )
    await target.fill(str(ctx.variables.require("采购订单.订单号")))


async def step_120_click(ctx: RunContext) -> None:
    """展开供应商自定义下拉框。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="供应商下拉框",
        locators=[
            {
                "strategy": "role",
                "role": "combobox",
                "name": "供应商",
                "exact": True,
            },
            {"strategy": "test_id", "value": "supplier-combobox"},
        ],
    )
    await target.click()


async def step_130_fill(ctx: RunContext) -> None:
    """使用采购订单.供应商搜索下拉选项。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="供应商搜索框",
        locators=[
            {"strategy": "placeholder", "value": "搜索供应商", "exact": True},
            {"strategy": "test_id", "value": "supplier-search"},
        ],
    )
    await target.fill(str(ctx.variables.require("采购订单.供应商")))


async def step_140_click(ctx: RunContext) -> None:
    """点击与采购订单.供应商匹配的选项。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    supplier = str(ctx.variables.require("采购订单.供应商"))
    target = await _target(
        ctx,
        scope,
        name="与采购订单供应商匹配的选项",
        path=[
            {
                "name": "供应商选项列表",
                "locators": [
                    {
                        "strategy": "role",
                        "role": "listbox",
                        "name": "供应商选项",
                        "exact": True,
                    },
                    {"strategy": "test_id", "value": "supplier-options"},
                ],
            },
            {
                "name": "供应商匹配项",
                "locators": [{"strategy": "role", "role": "option"}],
                "filter_text": supplier,
            },
        ],
        locators=[{"strategy": "css", "value": '[data-testid="option-label"]'}],
    )
    await target.click()


async def step_150_fill(ctx: RunContext) -> None:
    """填写合同号。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="合同号",
        locators=[
            {"strategy": "label", "value": "合同号", "exact": True},
            {"strategy": "test_id", "value": "contract-no"},
        ],
    )
    await target.fill(str(ctx.variables.require("采购订单.合同号")))


async def step_160_fill(ctx: RunContext) -> None:
    """填写验收金额。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="验收金额",
        locators=[
            {"strategy": "label", "value": "验收金额", "exact": True},
            {"strategy": "test_id", "value": "acceptance-amount"},
        ],
    )
    await target.fill(str(ctx.variables.require("采购订单.含税金额")))


async def step_170_click(ctx: RunContext) -> None:
    """展开币种自定义下拉框。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="币种下拉框",
        locators=[
            {
                "strategy": "role",
                "role": "combobox",
                "name": "币种",
                "exact": True,
            },
            {"strategy": "test_id", "value": "currency-combobox"},
        ],
    )
    await target.click()


async def step_180_click(ctx: RunContext) -> None:
    """点击与采购订单.币种匹配的选项。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    currency = str(ctx.variables.require("采购订单.币种"))
    target = await _target(
        ctx,
        scope,
        name="与采购订单币种匹配的选项",
        path=[
            {
                "name": "币种选项列表",
                "locators": [
                    {
                        "strategy": "role",
                        "role": "listbox",
                        "name": "币种选项",
                        "exact": True,
                    },
                    {"strategy": "test_id", "value": "currency-options"},
                ],
            },
            {
                "name": "币种匹配项",
                "locators": [{"strategy": "role", "role": "option"}],
                "filter_text": currency,
            },
        ],
        locators=[{"strategy": "css", "value": '[data-testid="option-label"]'}],
    )
    await target.click()


async def step_190_fill(ctx: RunContext) -> None:
    """填写订单日期。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="订单日期",
        locators=[
            {"strategy": "label", "value": "订单日期", "exact": True},
            {"strategy": "test_id", "value": "order-date"},
        ],
    )
    await target.fill(str(ctx.variables.require("采购订单.订单日期")))


async def step_200_fill(ctx: RunContext) -> None:
    """填写明确的业务常量“自动创建”。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="验收说明",
        locators=[
            {"strategy": "label", "value": "验收说明", "exact": True},
            {"strategy": "test_id", "value": "acceptance-note"},
        ],
    )
    await target.fill("自动创建")


async def step_210_set_checked(ctx: RunContext) -> None:
    """幂等勾选信息确认。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="信息确认",
        locators=[
            {
                "strategy": "role",
                "role": "checkbox",
                "name": "信息确认",
                "exact": True,
            },
            {"strategy": "test_id", "value": "information-confirmed"},
        ],
    )
    await target.check()


async def step_220_click(ctx: RunContext) -> None:
    """保存并等待 DOM 确认模态框。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="保存验收登记",
        locators=[
            {"strategy": "role", "role": "button", "name": "保存", "exact": True},
            {"strategy": "test_id", "value": "save-acceptance"},
        ],
    )
    await target.click()
    dialog = await _target(
        ctx,
        scope,
        name="提交确认模态框",
        locators=[
            {
                "strategy": "role",
                "role": "dialog",
                "name": "确认提交",
                "exact": True,
            },
            {"strategy": "test_id", "value": "submit-confirmation-dialog"},
        ],
    )
    await dialog.wait_for(state="visible")


async def step_230_click(ctx: RunContext) -> None:
    """在 DOM 模态框中确认提交。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="确认提交按钮",
        path=[
            {
                "name": "提交确认模态框",
                "locators": [
                    {
                        "strategy": "role",
                        "role": "dialog",
                        "name": "确认提交",
                        "exact": True,
                    },
                    {"strategy": "test_id", "value": "submit-confirmation-dialog"},
                ],
            }
        ],
        locators=[
            {
                "strategy": "role",
                "role": "button",
                "name": "确认提交",
                "exact": True,
            },
            {"strategy": "test_id", "value": "confirm-submit"},
        ],
    )
    await target.click()
    result = await _target(
        ctx,
        scope,
        name="保存成功结果",
        locators=[
            {
                "strategy": "role",
                "role": "status",
                "name": "保存成功",
                "exact": True,
            },
            {"strategy": "test_id", "value": "acceptance-success"},
        ],
    )
    await result.wait_for(state="visible")


async def step_240_extract(ctx: RunContext) -> None:
    """提取辅助成功提示并写入声明输出；E2E 真值仍由后端 Oracle 判断。"""
    scope = await _scope(ctx, "acceptance_detail", ACCEPTANCE_FRAME_PATH)
    target = await _target(
        ctx,
        scope,
        name="保存成功结果",
        locators=[
            {
                "strategy": "role",
                "role": "status",
                "name": "保存成功",
                "exact": True,
            },
            {"strategy": "test_id", "value": "acceptance-success"},
        ],
    )
    ctx.variables.write("验收结果", await target.inner_text())


async def run_browser_segment(ctx: RunContext) -> None:
    """按 CoreTrace sequence 顺序执行确定性浏览器段。"""
    await _run_step(ctx, trace_id="trace_010", sequence=10, action_kind="navigate", label="打开系统 A", operation=lambda: step_010_navigate(ctx))
    await _run_step(ctx, trace_id="trace_020", sequence=20, action_kind="click", label="展开业务类型", operation=lambda: step_020_click(ctx))
    await _run_step(ctx, trace_id="trace_030", sequence=30, action_kind="click", label="选择业务类型", operation=lambda: step_030_click(ctx))
    await _run_step(ctx, trace_id="trace_040", sequence=40, action_kind="fill", label="填写开始日期", operation=lambda: step_040_fill(ctx))
    await _run_step(ctx, trace_id="trace_050", sequence=50, action_kind="fill", label="填写结束日期", operation=lambda: step_050_fill(ctx))
    await _run_step(ctx, trace_id="trace_060", sequence=60, action_kind="fill", label="填写供应商", operation=lambda: step_060_fill(ctx))
    await _run_step(ctx, trace_id="trace_070", sequence=70, action_kind="fill", label="填写订单编号", operation=lambda: step_070_fill(ctx))
    await _run_step(ctx, trace_id="trace_080", sequence=80, action_kind="click", label="查询采购订单", operation=lambda: step_080_click(ctx))
    await _run_step(ctx, trace_id="trace_090", sequence=90, action_kind="agent", label="提取采购订单", operation=lambda: step_090_agent(ctx))
    await _run_step(ctx, trace_id="trace_100", sequence=100, action_kind="click", label="发起目标订单验收", operation=lambda: step_100_click(ctx))
    await _run_step(ctx, trace_id="trace_110", sequence=110, action_kind="fill", label="填写来源订单号", operation=lambda: step_110_fill(ctx))
    await _run_step(ctx, trace_id="trace_120", sequence=120, action_kind="click", label="展开供应商选项", operation=lambda: step_120_click(ctx))
    await _run_step(ctx, trace_id="trace_130", sequence=130, action_kind="fill", label="搜索供应商", operation=lambda: step_130_fill(ctx))
    await _run_step(ctx, trace_id="trace_140", sequence=140, action_kind="click", label="选择供应商", operation=lambda: step_140_click(ctx))
    await _run_step(ctx, trace_id="trace_150", sequence=150, action_kind="fill", label="填写合同号", operation=lambda: step_150_fill(ctx))
    await _run_step(ctx, trace_id="trace_160", sequence=160, action_kind="fill", label="填写验收金额", operation=lambda: step_160_fill(ctx))
    await _run_step(ctx, trace_id="trace_170", sequence=170, action_kind="click", label="展开币种选项", operation=lambda: step_170_click(ctx))
    await _run_step(ctx, trace_id="trace_180", sequence=180, action_kind="click", label="选择币种", operation=lambda: step_180_click(ctx))
    await _run_step(ctx, trace_id="trace_190", sequence=190, action_kind="fill", label="填写订单日期", operation=lambda: step_190_fill(ctx))
    await _run_step(ctx, trace_id="trace_200", sequence=200, action_kind="fill", label="填写验收说明", operation=lambda: step_200_fill(ctx))
    await _run_step(ctx, trace_id="trace_210", sequence=210, action_kind="set_checked", label="确认信息", operation=lambda: step_210_set_checked(ctx))
    await _run_step(ctx, trace_id="trace_220", sequence=220, action_kind="click", label="保存验收登记", operation=lambda: step_220_click(ctx))
    await _run_step(ctx, trace_id="trace_230", sequence=230, action_kind="click", label="确认提交", operation=lambda: step_230_click(ctx))
    await _run_step(ctx, trace_id="trace_240", sequence=240, action_kind="extract", label="提取验收结果", operation=lambda: step_240_extract(ctx))
