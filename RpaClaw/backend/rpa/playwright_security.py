RPA_RELAXED_CHROMIUM_ARGS = [
    "--ignore-certificate-errors",
    "--allow-insecure-localhost",
    "--allow-running-insecure-content",
    "--test-type",
    "--disable-notifications"
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
