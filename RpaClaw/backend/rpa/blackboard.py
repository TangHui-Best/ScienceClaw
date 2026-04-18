from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Blackboard:
    values: Dict[str, Any] = field(default_factory=dict)
    schema: Dict[str, Any] = field(default_factory=dict)
    runtime_params: Dict[str, Any] = field(default_factory=dict)

    def write(self, key: str, value: Any, schema: Any = None) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("blackboard key must be a non-empty string")
        self.values[key] = value
        if schema is not None:
            self.schema[key] = schema

    def resolve_ref(self, ref: str) -> Any:
        if not isinstance(ref, str) or not ref.strip():
            raise KeyError(str(ref))

        normalized_ref = ref.strip()
        if normalized_ref.startswith("params."):
            current: Any = self.runtime_params
            path = normalized_ref.removeprefix("params.").split(".")
        else:
            current = self.values
            path = normalized_ref.split(".")

        for segment in path:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
                continue
            if isinstance(current, list) and segment.isdigit():
                index = int(segment)
                if 0 <= index < len(current):
                    current = current[index]
                    continue
            raise KeyError(normalized_ref)

        return current


_TEMPLATE_REF = re.compile(r"\{([^{}]+)\}")


def resolve_template(template: str, board: Blackboard) -> str:
    def replace(match: re.Match[str]) -> str:
        return str(board.resolve_ref(match.group(1).strip()))

    return _TEMPLATE_REF.sub(replace, template or "")
