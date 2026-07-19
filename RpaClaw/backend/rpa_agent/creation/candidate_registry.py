"""人工动作与浏览器事实之间的短生命周期因果窗口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from threading import RLock
from typing import Iterable


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True, eq=False)
class CandidateReservation:
    """浏览器默认行为发生前创建的窗口凭据。"""

    candidate_id: str
    page_runtime_ref: str
    frame_runtime_ref: str
    window_id: int


@dataclass(frozen=True, slots=True, eq=False)
class LockedCandidate:
    """事实第一次触发时冻结的关联；异步完成只能携带此凭据。"""

    candidate_id: str
    window_id: int
    lock_id: int


class _WindowState(Enum):
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass(slots=True)
class _CandidateWindow:
    reservation: CandidateReservation
    state: _WindowState = _WindowState.ACTIVE
    fact_locks: dict[int, LockedCandidate] = field(default_factory=dict)
    tail_expires_at: datetime | None = None


class ActiveCandidateRegistry:
    """按 Page + Frame 隔离的显式 Candidate 窗口注册表。

    注册表不接受时间戳，也不提供跨作用域查找。关闭窗口后不能再锁定新事实，
    但关闭前已经锁定的异步事实仍可在显式过期前完成。
    """

    def __init__(self) -> None:
        self._active_by_scope: dict[tuple[str, str], _CandidateWindow] = {}
        self._windows: dict[int, _CandidateWindow] = {}
        self._used_candidate_ids: set[str] = set()
        self._next_window_id = 1
        self._next_lock_id = 1
        self._mutex = RLock()

    def reserve(
        self,
        *,
        candidate_id: str,
        page_runtime_ref: str,
        frame_runtime_ref: str,
    ) -> CandidateReservation:
        """在浏览器默认行为前，为一个精确 Page/Frame 预留窗口。"""

        self._validate_identifier(candidate_id, "candidate_id")
        self._validate_identifier(page_runtime_ref, "page_runtime_ref")
        self._validate_identifier(frame_runtime_ref, "frame_runtime_ref")
        scope = (page_runtime_ref, frame_runtime_ref)
        with self._mutex:
            if candidate_id in self._used_candidate_ids:
                raise ValueError(f"candidate_window.id_duplicate:{candidate_id}")
            if scope in self._active_by_scope:
                raise ValueError(
                    f"candidate_window.scope_occupied:{page_runtime_ref}:{frame_runtime_ref}"
                )
            reservation = CandidateReservation(
                candidate_id=candidate_id,
                page_runtime_ref=page_runtime_ref,
                frame_runtime_ref=frame_runtime_ref,
                window_id=self._next_window_id,
            )
            self._next_window_id += 1
            window = _CandidateWindow(reservation=reservation)
            self._active_by_scope[scope] = window
            self._windows[reservation.window_id] = window
            self._used_candidate_ids.add(candidate_id)
            return reservation

    def lock_fact(
        self, *, page_runtime_ref: str, frame_runtime_ref: str
    ) -> LockedCandidate | None:
        """在事实首次触发时同步锁定精确窗口；没有活动窗口则返回空。"""

        scope = (page_runtime_ref, frame_runtime_ref)
        with self._mutex:
            window = self._active_by_scope.get(scope)
            if window is None or window.state is not _WindowState.ACTIVE:
                return None
            lock_id = self._next_lock_id
            self._next_lock_id += 1
            locked = LockedCandidate(
                candidate_id=window.reservation.candidate_id,
                window_id=window.reservation.window_id,
                lock_id=lock_id,
            )
            window.fact_locks[lock_id] = locked
            return locked

    def complete_fact(
        self,
        locked: LockedCandidate | None,
        *,
        observed_at: datetime | None = None,
    ) -> str | None:
        """解析首次触发时的锁；空锁或已过期锁绝不重新关联。"""

        if locked is None:
            return None
        with self._mutex:
            window = self._windows.get(locked.window_id)
            if window is None:
                return None
            stored = window.fact_locks.get(locked.lock_id)
            if stored is not locked:
                return None
            del window.fact_locks[locked.lock_id]
            if (
                window.state is _WindowState.CLOSED
                and window.tail_expires_at is not None
            ):
                if observed_at is None:
                    return None
                try:
                    expired = observed_at >= window.tail_expires_at
                except TypeError as exc:
                    raise ValueError("candidate_window.timezone_mismatch") from exc
                if expired:
                    return None
            return locked.candidate_id

    def discard_fact_lock(self, locked: LockedCandidate | None) -> bool:
        """按对象身份释放一个未完成事实锁；伪造或已消费凭据无效。"""

        if locked is None:
            return False
        with self._mutex:
            window = self._windows.get(locked.window_id)
            if window is None:
                return False
            stored = window.fact_locks.get(locked.lock_id)
            if stored is not locked:
                return False
            del window.fact_locks[locked.lock_id]
            return True

    def validate_active(
        self,
        reservation: CandidateReservation,
        *,
        page_runtime_ref: str,
        frame_runtime_ref: str,
    ) -> str:
        """验证一个不可替换的凭据仍属于给定的活动 Page/Frame 窗口。"""

        with self._mutex:
            window = self._require_window(reservation)
            if window.state is not _WindowState.ACTIVE:
                raise ValueError("candidate_window.not_active")
            if (
                reservation.page_runtime_ref != page_runtime_ref
                or reservation.frame_runtime_ref != frame_runtime_ref
            ):
                raise ValueError("candidate_window.scope_mismatch")
            scope = (page_runtime_ref, frame_runtime_ref)
            if self._active_by_scope.get(scope) is not window:
                raise ValueError("candidate_window.reservation_mismatch")
            return reservation.candidate_id

    def close(
        self,
        reservation: CandidateReservation,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        """关闭活动窗口，只保留关闭前已经锁定的异步完成资格。"""

        self.close_many((reservation,), expires_at=expires_at)

    def validate_reservations(
        self, reservations: Iterable[CandidateReservation]
    ) -> None:
        """按对象身份原子预检一组仍由调用 Session 持有的窗口。"""

        items = tuple(reservations)
        with self._mutex:
            self._validate_many(items)

    def close_many(
        self,
        reservations: Iterable[CandidateReservation],
        *,
        expires_at: datetime | None = None,
    ) -> int:
        """全部凭据预检成功后才一次性关闭活动窗口。"""

        items = tuple(reservations)
        with self._mutex:
            windows = self._validate_many(items)
            closed = 0
            for window in windows:
                if window.state is _WindowState.CLOSED:
                    continue
                reservation = window.reservation
                scope = (
                    reservation.page_runtime_ref,
                    reservation.frame_runtime_ref,
                )
                del self._active_by_scope[scope]
                window.state = _WindowState.CLOSED
                window.tail_expires_at = expires_at
                closed += 1
            return closed

    def expire_closed(self, now: datetime) -> tuple[int, ...]:
        """释放已到有界尾期的关闭窗口及其全部未完成事实锁。"""

        with self._mutex:
            expired_ids: list[int] = []
            for window_id, window in tuple(self._windows.items()):
                if (
                    window.state is not _WindowState.CLOSED
                    or window.tail_expires_at is None
                ):
                    continue
                try:
                    expired = now >= window.tail_expires_at
                except TypeError as exc:
                    raise ValueError("candidate_window.timezone_mismatch") from exc
                if not expired:
                    continue
                window.fact_locks.clear()
                del self._windows[window_id]
                expired_ids.append(window_id)
            return tuple(expired_ids)

    def _validate_many(
        self, reservations: tuple[CandidateReservation, ...]
    ) -> tuple[_CandidateWindow, ...]:
        windows: list[_CandidateWindow] = []
        seen: set[int] = set()
        for reservation in reservations:
            window = self._require_window(reservation)
            if reservation.window_id in seen:
                continue
            seen.add(reservation.window_id)
            if window.state is _WindowState.ACTIVE:
                scope = (
                    reservation.page_runtime_ref,
                    reservation.frame_runtime_ref,
                )
                if self._active_by_scope.get(scope) is not window:
                    raise ValueError("candidate_window.reservation_mismatch")
            windows.append(window)
        return tuple(windows)

    def expire(self, reservation: CandidateReservation) -> None:
        """显式释放窗口并使全部未完成的事实锁失效。"""

        self.expire_many((reservation,))

    def expire_many(
        self, reservations: Iterable[CandidateReservation]
    ) -> int:
        """全量 identity 预检成功后才一次性删除窗口和锁。"""

        items = tuple(reservations)
        with self._mutex:
            windows = self._validate_many(items)
            for window in windows:
                reservation = window.reservation
                scope = (
                    reservation.page_runtime_ref,
                    reservation.frame_runtime_ref,
                )
                if self._active_by_scope.get(scope) is window:
                    del self._active_by_scope[scope]
                del self._windows[reservation.window_id]
                window.fact_locks.clear()
            return len(windows)

    def _require_window(self, reservation: CandidateReservation) -> _CandidateWindow:
        window = self._windows.get(reservation.window_id)
        if window is None or window.reservation is not reservation:
            raise ValueError("candidate_window.reservation_mismatch")
        return window

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> None:
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"candidate_window.{field_name}_invalid")
