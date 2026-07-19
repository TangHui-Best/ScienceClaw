from __future__ import annotations

from rpa_agent.runtime import RunContext, SkillRunResult

from .browser_segment import run_browser_segment


async def execute_skill(ctx: RunContext) -> SkillRunResult:
    """ScienceClaw 宿主调用的稳定入口。"""
    await run_browser_segment(ctx)
    return ctx.results.succeeded()
