"""一次 Skill Run 的完全隔离服务容器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from ..contracts import SkillDefinition
from .agent import AgentExecutor
from .effects import EffectCoordinator
from .frames import FrameResolver
from .locators import LocatorResolver
from .pages import PageRegistry
from .results import ResultBuilder
from .steps import StepExecutor, WaitExecutor
from .variables import (
    DataAssetHandle,
    DataAssetRegistry,
    InputStore,
    SecretResolver,
    VariableStore,
)


class RunContext:
    def __init__(
        self,
        *,
        run_id: str,
        definition: SkillDefinition,
        main_page: object,
        input_values: Mapping[str, object],
        secret_provider: Callable[[str], Awaitable[str | None]],
        asset_inputs: Mapping[str, DataAssetHandle] | None = None,
        agent_backend: Callable[..., Awaitable[Mapping[str, object]]] | None = None,
        expect_factory: Callable[[object], object] | None = None,
    ) -> None:
        if not run_id:
            raise ValueError("run_id.required")
        if not isinstance(definition, SkillDefinition):
            raise TypeError("definition.must_be_skill_definition")
        self.run_id = run_id
        self.inputs = InputStore(definition.inputs, input_values)
        self.secrets = SecretResolver(definition.secrets, secret_provider)
        self.variables = VariableStore({item.variable_ref: item.name for item in definition.outputs})
        self.assets = DataAssetRegistry(
            input_refs={item.ref for item in definition.asset_inputs},
            output_refs={item.asset_ref: item.name for item in definition.asset_outputs},
            initial=asset_inputs or {},
            required_input_refs={item.ref for item in definition.asset_inputs if item.required},
        )
        self.pages = PageRegistry(main_page)
        self.locators = LocatorResolver()
        self.frames = FrameResolver(self.locators)
        self.effects = EffectCoordinator(self.pages, self.assets)
        self.agent = AgentExecutor(agent_backend)
        self.results = ResultBuilder(
            run_id,
            output_refs={item.name for item in definition.outputs},
            asset_refs={item.name for item in definition.asset_outputs},
        )
        self.steps = StepExecutor(run_id, self.effects, self.results)
        self.waits = WaitExecutor(self.locators, expect_factory=expect_factory)

    def __repr__(self) -> str:
        return f"RunContext(run_id={self.run_id!r}, services=<isolated>)"
