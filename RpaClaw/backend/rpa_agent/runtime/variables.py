"""运行期 Input、Secret、Variable 与 DataAsset 命名空间。"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping

from .results import RuntimeServiceError


class InputValidationError(ValueError):
    pass


class VariableStoreError(RuntimeServiceError):
    def __init__(self, value: str, *, phase: str = "output") -> None:
        code = value.split(":", 1)[0]
        super().__init__(phase=phase, code=code, safe_message="VariableStore 契约校验失败")


class DataAssetRegistryError(RuntimeServiceError):
    def __init__(self, value: str, *, phase: str) -> None:
        code = value.split(":", 1)[0]
        super().__init__(phase=phase, code=code, safe_message="DataAsset 契约校验失败")


class SecretResolutionError(RuntimeServiceError):
    def __init__(self, value: str) -> None:
        code = value.split(":", 1)[0]
        super().__init__(phase="input", code=code, safe_message="Secret 无法读取")


class InputStore:
    def __init__(self, definitions: list[object], values: Mapping[str, object]) -> None:
        declared = {getattr(item, "ref"): item for item in definitions}
        unknown = set(values) - set(declared)
        if unknown:
            raise InputValidationError("input.unknown")
        resolved: dict[str, object] = {}
        for ref, item in declared.items():
            if ref in values:
                value = values[ref]
            elif "default" in getattr(item, "model_fields_set", set()):
                value = getattr(item, "default")
            elif getattr(item, "required"):
                raise InputValidationError(f"input.required:{ref}")
            else:
                continue
            if not _matches_type(value, getattr(item, "value_type")):
                raise InputValidationError(f"input.type:{ref}")
            resolved[ref] = value
        self._values = resolved

    def require(self, ref: str) -> object:
        if ref not in self._values:
            raise RuntimeServiceError(
                phase="input", code="input.missing", safe_message="Skill Input 缺失"
            )
        return self._values[ref]


def _matches_type(value: object, value_type: str) -> bool:
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "boolean":
        return type(value) is bool
    if value_type == "number":
        return type(value) in (int, float)
    return False


class ResolvedSecret(str):
    _rpa_secret = True

    def __repr__(self) -> str:
        return "<redacted>"


class SecretResolver:
    def __init__(
        self,
        definitions: list[object],
        provider: Callable[[str], Awaitable[str | None]],
    ) -> None:
        self._definitions = {getattr(item, "ref"): item for item in definitions}
        self._provider = provider

    async def require(self, ref: str) -> ResolvedSecret:
        if ref not in self._definitions:
            raise SecretResolutionError(f"secret.not_declared:{ref}")
        provider_failed = False
        try:
            value = await self._provider(ref)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except BaseException:
            provider_failed = True
            value = None
        if provider_failed:
            raise SecretResolutionError("secret.provider_failed")
        if value is None or not isinstance(value, str):
            raise SecretResolutionError(f"secret.missing:{ref}")
        return ResolvedSecret(value)

    def __repr__(self) -> str:
        return "SecretResolver(<redacted>)"


class VariableStore:
    def __init__(self, declared_outputs: Mapping[str, str]) -> None:
        self._roots: dict[str, object] = {}
        self._written: set[str] = set()
        self._declared_outputs = dict(declared_outputs)

    def contains(self, ref: str) -> bool:
        try:
            self.require(ref)
        except RuntimeServiceError:
            return False
        return True

    def require(self, ref: str) -> object:
        parts = _parts(ref)
        if parts[0] not in self._roots:
            raise VariableStoreError(f"variable.missing:{ref}", phase="input")
        current = self._roots[parts[0]]
        for part in parts[1:]:
            if not isinstance(current, dict) or part not in current:
                raise VariableStoreError(f"variable.missing:{ref}", phase="input")
            current = current[part]
        return _clone_value(current)

    def write(self, ref: str, value: object) -> None:
        if _contains_secret(value):
            raise VariableStoreError("variable.secret_forbidden")
        stored_value = _clone_value(value)
        parts = _parts(ref)
        if ref in self._written or (len(parts) == 1 and parts[0] in self._roots):
            raise VariableStoreError(f"variable.duplicate_write:{ref}")
        root = parts[0]
        if len(parts) > 1 and root in self._written:
            raise VariableStoreError(f"variable.path_conflict:{ref}")
        if len(parts) == 1:
            if root in self._roots:
                raise VariableStoreError(f"variable.path_conflict:{ref}")
            self._roots[root] = stored_value
            self._written.add(ref)
            return
        if root not in self._roots:
            self._roots[root] = {}
        current = self._roots[root]
        for part in parts[1:-1]:
            if not isinstance(current, dict):
                raise VariableStoreError(f"variable.path_conflict:{ref}")
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                raise VariableStoreError(f"variable.path_conflict:{ref}")
            current = current[part]
        if not isinstance(current, dict) or parts[-1] in current:
            raise VariableStoreError(f"variable.path_conflict:{ref}")
        current[parts[-1]] = stored_value
        self._written.add(ref)

    def export(self, refs: tuple[str, ...]) -> dict[str, object]:
        result: dict[str, object] = {}
        for ref in refs:
            if ref not in self._declared_outputs:
                raise VariableStoreError(f"variable.output_not_declared:{ref}")
            result[self._declared_outputs[ref]] = self.require(ref)
        return result

    def snapshot(self) -> dict[str, object]:
        """Return all non-sensitive values produced by earlier steps."""

        return _clone_value(self._roots)


def _parts(ref: str) -> list[str]:
    parts = ref.split(".")
    if not all(parts):
        raise VariableStoreError("variable.ref_invalid")
    return parts


def _contains_secret(value: object) -> bool:
    if getattr(value, "_rpa_secret", False) is True:
        return True
    if isinstance(value, Mapping):
        return any(_contains_secret(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_secret(item) for item in value)
    return False


def _clone_value(value: object) -> object:
    try:
        return copy.deepcopy(value)
    except Exception as exc:
        raise VariableStoreError("variable.value_not_isolatable") from exc


@dataclass(frozen=True, slots=True)
class DataAssetHandle:
    ref: str
    runtime_value: object = field(repr=False)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(copy.deepcopy(dict(self.metadata))))

    def __fspath__(self) -> str:
        if not isinstance(self.runtime_value, str):
            raise TypeError("asset runtime value is not path-like")
        return self.runtime_value

    def public_contract(self) -> dict[str, object]:
        safe = {"ref": self.ref}
        for key in ("name", "media_type", "size"):
            if key in self.metadata:
                value = self.metadata[key]
                if isinstance(value, str) and Path(value).is_absolute():
                    continue
                safe[key] = copy.deepcopy(value)
        return safe


class DataAssetRegistry:
    def __init__(
        self,
        *,
        input_refs: set[str],
        output_refs: Mapping[str, str],
        initial: Mapping[str, DataAssetHandle],
        required_input_refs: set[str] | None = None,
    ) -> None:
        unknown = set(initial) - input_refs
        if unknown:
            raise DataAssetRegistryError("asset.input_not_declared", phase="input")
        missing = set(required_input_refs or ()) - set(initial)
        if missing:
            raise DataAssetRegistryError("asset.required", phase="input")
        self._output_refs = dict(output_refs)
        self._assets = dict(initial)

    def require(self, ref: str) -> DataAssetHandle:
        if ref not in self._assets:
            raise DataAssetRegistryError(f"asset.missing:{ref}", phase="input")
        return self._assets[ref]

    def register(self, ref: str, value: object) -> None:
        if ref in self._assets:
            raise DataAssetRegistryError(f"asset.duplicate:{ref}", phase="output")
        if ref not in self._output_refs:
            raise DataAssetRegistryError(f"asset.output_not_declared:{ref}", phase="output")
        handle = value if isinstance(value, DataAssetHandle) else DataAssetHandle(ref, value)
        if handle.ref != ref:
            raise ValueError("asset.ref_mismatch")
        self._assets[ref] = handle

    def export(self, refs: tuple[str, ...], *, allow_missing: bool = False) -> dict[str, object]:
        result: dict[str, object] = {}
        for ref in refs:
            if ref not in self._output_refs:
                raise DataAssetRegistryError(f"asset.output_not_declared:{ref}", phase="output")
            if ref not in self._assets:
                if allow_missing:
                    continue
                raise DataAssetRegistryError(f"asset.missing:{ref}", phase="output")
            result[self._output_refs[ref]] = self._assets[ref].public_contract()
        return result
