"""Browser-use LLM 的最小、强类型、安全白名单上下文。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..creation.session import SessionVariableStore


_NAME = re.compile(r"^[^\s:/\\]+$")
_VARIABLE_REF = re.compile(r"^[^.\s]+(?:\.[^.\s]+)*$")
_TOKEN = re.compile(
    r"(?i)(?:token|secret|api[_-]?key|password|passwd|pwd|credentials?)\s*[:=]"
)
_SENSITIVE_KEY = re.compile(
    r"(?i)^(?:token|secret|api[_-]?key|password|passwd|pwd|credentials?)$"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_PRIVATE_TERMS = re.compile(
    r"(?i)(?:browser[-_ ]?use\s+history|runtime[_ -]?(?:page|frame)(?:[_ -]?id)?|"
    r"session[_ -]?id|core[_ -]?trace\s+timeline)"
)


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("browser_use_context.not_json_safe") from exc


def _contains_absolute_path(value: Any) -> bool:
    if isinstance(value, str):
        return (
            Path(value).is_absolute()
            or PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).is_absolute()
        )
    if isinstance(value, Mapping):
        return any(
            _contains_absolute_path(key) or _contains_absolute_path(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_absolute_path(item) for item in value)
    return False


def _contains_unsafe_content(value: Any) -> bool:
    if _contains_absolute_path(value):
        return True
    if isinstance(value, str):
        return any(pattern.search(value) is not None for pattern in (_TOKEN, _BEARER, _JWT, _PRIVATE_TERMS))
    if isinstance(value, Mapping):
        return any(
            (
                isinstance(key, str)
                and _SENSITIVE_KEY.fullmatch(key.strip()) is not None
            )
            or _contains_unsafe_content(key)
            or _contains_unsafe_content(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unsafe_content(item) for item in value)
    return False


def _require_safe(value: Any) -> None:
    if _contains_unsafe_content(value):
        raise ValueError("browser_use_context.unsafe_content")


@dataclass(frozen=True, slots=True)
class BrowserPageState:
    title: str
    url: str
    interactive_elements: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("browser_use_context.page_title_invalid")
        if not isinstance(self.url, str) or not self.url.strip():
            raise ValueError("browser_use_context.page_url_invalid")
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("browser_use_context.page_url_invalid")
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or _contains_unsafe_content(self.url)
        ):
            raise ValueError("browser_use_context.page_url_unsafe")
        elements = tuple(self.interactive_elements)
        if any(not isinstance(item, str) or not item.strip() for item in elements):
            raise ValueError("browser_use_context.page_element_invalid")
        _require_safe((self.title, elements))
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "interactive_elements", elements)


def _validate_named_purposes(value: Mapping[str, str]) -> dict[str, str]:
    copied = _json_copy(dict(value))
    for name, purpose in copied.items():
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise ValueError("browser_use_context.name_invalid")
        if not isinstance(purpose, str) or not purpose.strip():
            raise ValueError("browser_use_context.purpose_invalid")
    _require_safe(copied)
    return copied


@dataclass(frozen=True, slots=True)
class BrowserUseContextRequest:
    """一次指令的显式白名单；不接受 Session、Timeline 或 History 对象。"""

    current_instruction: str
    current_page_state: BrowserPageState
    business_terms: tuple[str, ...]
    required_variable_refs: tuple[str, ...]
    allowed_inputs: Mapping[str, str] = field(compare=True)
    allowed_secret_names: tuple[str, ...] = field(compare=True)
    allowed_data_assets: Mapping[str, str] = field(compare=True)
    page_aliases: Mapping[str, str] = field(compare=True)

    def __post_init__(self) -> None:
        if not isinstance(self.current_instruction, str) or not self.current_instruction.strip():
            raise ValueError("browser_use_context.instruction_invalid")
        if not isinstance(self.current_page_state, BrowserPageState):
            raise TypeError("browser_use_context.page_state_invalid")
        terms = tuple(self.business_terms)
        if any(not isinstance(term, str) or not term.strip() for term in terms):
            raise ValueError("browser_use_context.business_term_invalid")
        refs = tuple(self.required_variable_refs)
        if any(not isinstance(ref, str) or _VARIABLE_REF.fullmatch(ref) is None for ref in refs):
            raise ValueError("browser_use_context.variable_ref_invalid")
        if len(refs) != len(set(refs)):
            raise ValueError("browser_use_context.variable_ref_duplicate")
        secret_names = tuple(self.allowed_secret_names)
        if any(not isinstance(name, str) or _NAME.fullmatch(name) is None for name in secret_names):
            raise ValueError("browser_use_context.name_invalid")
        if len(secret_names) != len(set(secret_names)):
            raise ValueError("browser_use_context.secret_name_duplicate")
        _require_safe((self.current_instruction, terms, refs, secret_names))
        object.__setattr__(self, "current_instruction", self.current_instruction.strip())
        object.__setattr__(self, "business_terms", terms)
        object.__setattr__(self, "required_variable_refs", refs)
        object.__setattr__(self, "allowed_secret_names", secret_names)
        object.__setattr__(self, "allowed_inputs", _validate_named_purposes(self.allowed_inputs))
        object.__setattr__(self, "allowed_data_assets", _validate_named_purposes(self.allowed_data_assets))
        object.__setattr__(self, "page_aliases", _validate_named_purposes(self.page_aliases))


def build_minimal_context(
    request: BrowserUseContextRequest,
    *,
    variables: SessionVariableStore,
) -> dict[str, Any]:
    """只读取当前指令声明的变量，并在最终边界再次检查完整输出。"""

    selected = {ref: variables.read(ref) for ref in request.required_variable_refs}
    context = {
        "current_instruction": request.current_instruction,
        "current_page_state": asdict(request.current_page_state),
        "business_terms": list(request.business_terms),
        "variables": selected,
        "allowed_inputs": dict(request.allowed_inputs),
        "allowed_secret_names": list(request.allowed_secret_names),
        "allowed_data_assets": dict(request.allowed_data_assets),
        "page_aliases": dict(request.page_aliases),
    }
    _require_safe(context)
    return _json_copy(deepcopy(context))
