"""创建态运行页面到稳定 PageRef 的顺序化映射。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from threading import RLock

from pydantic import BaseModel, TypeAdapter

from ..contracts.models import BrowserFact


_FACT_ADAPTER = TypeAdapter(BrowserFact)


@dataclass(slots=True)
class _PageState:
    page_ref: str
    runtime_ref: str
    closed: bool = False
    current_url: str | None = None


class PageRegistry:
    def __init__(self, *, main_runtime_ref: str) -> None:
        self._runtime_pages = {
            main_runtime_ref: _PageState(page_ref="main", runtime_ref=main_runtime_ref)
        }
        self._pages = {"main": self._runtime_pages[main_runtime_ref]}
        self._fact_fingerprints: dict[str, str] = {}
        self._fact_results: dict[str, str | None] = {}
        self._page_producers: dict[str, str] = {}
        self._last_observed_order = 0
        self._next_page_number = 1
        self._active_page_ref: str | None = "main"
        self._mutex = RLock()

    @property
    def active_page_ref(self) -> str | None:
        with self._mutex:
            return self._active_page_ref

    @property
    def runtime_state_count(self) -> int:
        with self._mutex:
            return len(self._runtime_pages)

    def resolve(self, runtime_page_ref: str) -> str:
        with self._mutex:
            state = self._runtime_pages.get(runtime_page_ref)
            if state is None:
                raise ValueError(f"page_registry.runtime_page_unknown:{runtime_page_ref}")
            return state.page_ref

    def has_page_ref(self, page_ref: str, *, include_closed: bool = False) -> bool:
        with self._mutex:
            state = self._pages.get(page_ref)
            return state is not None and (include_closed or not state.closed)

    def is_closed(self, page_ref: str) -> bool:
        with self._mutex:
            state = self._pages.get(page_ref)
            if state is None:
                raise ValueError(f"page_registry.page_unknown:{page_ref}")
            return state.closed

    def producer_snapshot(self) -> dict[str, str]:
        with self._mutex:
            return dict(self._page_producers)

    def clear(self) -> None:
        """销毁创建态运行页面、随机 URL 指纹和生产者索引。"""

        with self._mutex:
            self._runtime_pages.clear()
            self._pages.clear()
            self._fact_fingerprints.clear()
            self._fact_results.clear()
            self._page_producers.clear()
            self._active_page_ref = None

    def apply(self, fact: BrowserFact) -> str | None:
        """按 observed_order 应用；相同事实重试幂等，内容冲突 fail-closed。"""

        payload = fact.model_dump(mode="python") if isinstance(fact, BaseModel) else fact
        fact = _FACT_ADAPTER.validate_python(payload)
        with self._mutex:
            fingerprint = self._fingerprint(fact)
            previous = self._fact_fingerprints.get(fact.fact_id)
            if previous is not None:
                if previous != fingerprint:
                    raise ValueError(f"page_registry.fact_id_conflict:{fact.fact_id}")
                return self._fact_results[fact.fact_id]
            if fact.observed_order <= self._last_observed_order:
                raise ValueError(
                    f"page_registry.observed_order_regressed:{fact.observed_order}"
                )

            result = self._apply_new_fact(fact)
            self._fact_fingerprints[fact.fact_id] = fingerprint
            self._fact_results[fact.fact_id] = result
            self._last_observed_order = fact.observed_order
            return result

    def _apply_new_fact(self, fact: BrowserFact) -> str | None:
        runtime_ref = fact.runtime_scope.page_runtime_ref
        if fact.kind == "new_page":
            if runtime_ref in self._runtime_pages:
                raise ValueError(f"page_registry.runtime_page_conflict:{runtime_ref}")
            page_ref = f"page_{self._next_page_number:03d}"
            self._next_page_number += 1
            state = _PageState(
                page_ref=page_ref,
                runtime_ref=runtime_ref,
                current_url=fact.detail.initial_url,
            )
            self._runtime_pages[runtime_ref] = state
            self._pages[page_ref] = state
            if fact.candidate_id is not None:
                self._page_producers[page_ref] = fact.candidate_id
            return page_ref

        state = self._runtime_pages.get(runtime_ref)
        if state is None:
            raise ValueError(f"page_registry.runtime_page_unknown:{runtime_ref}")
        if fact.kind == "navigation":
            if state.closed:
                raise ValueError(f"page_registry.page_closed:{state.page_ref}")
            state.current_url = fact.detail.url
        elif fact.kind == "page_activated":
            if state.closed:
                raise ValueError(f"page_registry.page_closed:{state.page_ref}")
            self._active_page_ref = state.page_ref
        elif fact.kind == "page_closed":
            if state.closed:
                raise ValueError(f"page_registry.page_already_closed:{state.page_ref}")
            state.closed = True
            if self._active_page_ref == state.page_ref:
                open_pages = sorted(
                    (item.page_ref for item in self._pages.values() if not item.closed),
                    key=lambda ref: (ref != "main", ref),
                )
                self._active_page_ref = open_pages[0] if open_pages else None
        return state.page_ref

    @staticmethod
    def _fingerprint(fact: BrowserFact) -> str:
        payload = fact.model_dump(mode="json")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
