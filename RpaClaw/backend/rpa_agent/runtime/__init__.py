"""RPA Agent Runtime v0.1 公共接口。"""

from .agent import AgentExecutionError, AgentExecutor
from .context import RunContext
from .effects import EffectCoordinator, EffectHandle
from .frames import FrameResolutionError, FrameResolver
from .locators import LocatorResolutionError, LocatorResolver
from .pages import PageRegistry, PageRegistryError
from .results import (
    ResultBuilder,
    RuntimeServiceError,
    SkillRunResult,
    StepExecutionError,
    StepRecord,
)
from .steps import StepExecutor, WaitExecutor
from .variables import (
    DataAssetHandle,
    DataAssetRegistry,
    DataAssetRegistryError,
    InputStore,
    InputValidationError,
    SecretResolver,
    SecretResolutionError,
    VariableStore,
    VariableStoreError,
)

__all__ = [
    "AgentExecutionError",
    "AgentExecutor",
    "DataAssetHandle",
    "DataAssetRegistry",
    "DataAssetRegistryError",
    "EffectCoordinator",
    "EffectHandle",
    "FrameResolutionError",
    "FrameResolver",
    "InputStore",
    "InputValidationError",
    "LocatorResolutionError",
    "LocatorResolver",
    "PageRegistry",
    "PageRegistryError",
    "ResultBuilder",
    "RunContext",
    "RuntimeServiceError",
    "SecretResolver",
    "SecretResolutionError",
    "SkillRunResult",
    "StepExecutionError",
    "StepExecutor",
    "StepRecord",
    "VariableStore",
    "VariableStoreError",
    "WaitExecutor",
]
