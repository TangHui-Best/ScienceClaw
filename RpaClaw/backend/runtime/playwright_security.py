from __future__ import annotations


RPA_RELAXED_CHROMIUM_ARGS = [
    "--disable-cache",
    "--activate-on-launch",
    "--disable-features=MediaRouter,WebUsb,WebHid,Serial,Discovery,NetworkPrediction",
    "--disable-background-networking",
    "--disable-client-side-phishing-detection",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-web-security",
    "--allow-running-insecure-content",
    "--disable-features=PermissionsAPI",
]

RPA_CONTEXT_KWARGS = {
    "no_viewport": True,
    "accept_downloads": True,
    "ignore_https_errors": True,
}


def get_chromium_launch_kwargs(*, headless: bool) -> dict:
    return {
        "headless": headless,
        "args": list(RPA_RELAXED_CHROMIUM_ARGS),
    }


def get_context_kwargs(**overrides) -> dict:
    kwargs = dict(RPA_CONTEXT_KWARGS)
    kwargs.update(overrides)
    return kwargs


__all__ = [
    "RPA_CONTEXT_KWARGS",
    "RPA_RELAXED_CHROMIUM_ARGS",
    "get_chromium_launch_kwargs",
    "get_context_kwargs",
]
