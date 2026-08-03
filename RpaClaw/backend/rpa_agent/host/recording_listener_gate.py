"""Pauseable host-event subscription for the vNext manual recording path."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from .browser_session import HostBrowserEvent, HostDownloadEvent


class ManualRecordingListenerGate:
    """Routes browser events only while a human recording window is active.

    Browser-use actions deliberately do not enter this sink while the gate is
    paused.  This prevents AI-internal navigation/downloads from being
    accidentally attributed to the current manual Draft.
    """

    _KINDS = ("navigation", "new_page", "download")

    def __init__(
        self,
        *,
        port: object,
        event_sink: Callable[[HostBrowserEvent | HostDownloadEvent], None],
    ) -> None:
        self._port = port
        self._event_sink = event_sink
        self._releases: list[Callable[[], None]] = []
        self._attached = False
        self._paused = False
        self._mutex = RLock()

    @property
    def paused(self) -> bool:
        with self._mutex:
            return self._paused

    def attach(self) -> None:
        with self._mutex:
            if self._attached:
                raise ValueError("next_recording_listener.already_attached")
            subscribe = getattr(self._port, "subscribe", None)
            if not callable(subscribe):
                raise ValueError("next_recording_listener.subscribe_unavailable")
            releases: list[Callable[[], None]] = []
            try:
                for kind in self._KINDS:
                    releases.append(subscribe(kind, self._on_event))
            except BaseException:
                for release in reversed(releases):
                    release()
                raise
            self._releases = releases
            self._attached = True

    async def pause_manual_recording(self) -> None:
        with self._mutex:
            self._paused = True

    async def resume_manual_recording(self) -> None:
        with self._mutex:
            self._paused = False

    async def aclose(self) -> None:
        with self._mutex:
            releases = tuple(self._releases)
            self._releases = []
            self._attached = False
            self._paused = True
        for release in reversed(releases):
            release()

    def _on_event(self, event: HostBrowserEvent | HostDownloadEvent) -> None:
        with self._mutex:
            if self._paused:
                return
        self._event_sink(event)
