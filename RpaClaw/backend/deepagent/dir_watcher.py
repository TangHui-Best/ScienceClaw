"""Lightweight change detection for configurable tool and skill directories."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, FrozenSet, Tuple

from loguru import logger

_Snapshot = Tuple[FrozenSet[str], float]


class DirWatcher:
    """Track whether a directory's file list or max mtime has changed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: Dict[str, _Snapshot] = {}

    @staticmethod
    def _take_snapshot(dir_path: str) -> _Snapshot:
        base_path = Path(dir_path)
        if not base_path.is_dir():
            return frozenset(), 0.0

        files: set[str] = set()
        max_mtime = 0.0
        for file_path in base_path.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                try:
                    modified_time = file_path.stat().st_mtime
                except OSError:
                    modified_time = 0.0
                files.add(str(file_path.relative_to(base_path)))
                max_mtime = max(max_mtime, modified_time)
        return frozenset(files), max_mtime

    def has_changed(self, dir_path: str) -> bool:
        """Return whether the directory contents changed since the last snapshot."""

        with self._lock:
            current = self._take_snapshot(dir_path)
            previous = self._snapshots.get(dir_path)
            self._snapshots[dir_path] = current
            if previous is None:
                logger.info("[DirWatcher] Initialized snapshot for {} ({} files)", dir_path, len(current[0]))
                return False

            changed = current != previous
            if changed:
                old_files, _ = previous
                new_files, _ = current
                added = sorted(new_files - old_files)
                removed = sorted(old_files - new_files)
                parts: list[str] = []
                if added:
                    parts.append(f"added={added}")
                if removed:
                    parts.append(f"removed={removed}")
                if not added and not removed:
                    parts.append("contents_modified")
                logger.info("[DirWatcher] Detected change for {}: {}", dir_path, ", ".join(parts))
            return changed


watcher = DirWatcher()
