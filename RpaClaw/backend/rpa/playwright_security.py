"""Compatibility exports for browser host security settings."""

from backend.runtime.playwright_security import (
    RPA_CONTEXT_KWARGS,
    RPA_RELAXED_CHROMIUM_ARGS,
    get_chromium_launch_kwargs,
    get_context_kwargs,
)


__all__ = [
    "RPA_CONTEXT_KWARGS",
    "RPA_RELAXED_CHROMIUM_ARGS",
    "get_chromium_launch_kwargs",
    "get_context_kwargs",
]
