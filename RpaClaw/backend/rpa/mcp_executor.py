from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from backend.config import settings
from backend.rpa.generator import PlaywrightGenerator


class InvalidCookieError(ValueError):
    pass


class RpaMcpExecutor:
    def __init__(self, *, browser_factory=None, script_runner=None) -> None:
        self._browser_factory = browser_factory
        self._script_runner = script_runner or self._default_runner
        self._generator = PlaywrightGenerator()

    def validate_cookies(self, *, cookies: list[dict[str, Any]], allowed_domains: list[str], post_auth_start_url: str) -> list[dict[str, Any]]:
        if not isinstance(cookies, list) or not cookies:
            raise InvalidCookieError("cookies must be a non-empty array")
        allowed = {domain.lstrip('.').lower() for domain in allowed_domains}
        target_host = (urlparse(post_auth_start_url).hostname or '').lstrip('.').lower()
        for item in cookies:
            if not item.get('name') or not item.get('value'):
                raise InvalidCookieError('each cookie requires name and value')
            raw_domain = str(item.get('domain') or urlparse(str(item.get('url') or '')).hostname or '')
            domain = raw_domain.lstrip('.').lower()
            if not domain:
                raise InvalidCookieError('each cookie requires domain or url')
            if allowed and domain not in allowed and not any(domain.endswith(f'.{candidate}') for candidate in allowed):
                raise InvalidCookieError('cookie domain is not allowed')
        if target_host and allowed and target_host not in allowed and not any(target_host.endswith(f'.{candidate}') for candidate in allowed):
            raise InvalidCookieError('post-auth start URL is not within allowed domains')
        return cookies

    async def execute(self, tool, arguments: dict[str, Any]) -> dict[str, Any]:
        cookies = self.validate_cookies(
            cookies=list(arguments.get('cookies') or []),
            allowed_domains=list(tool.allowed_domains or []),
            post_auth_start_url=tool.post_auth_start_url,
        )
        kwargs = {key: value for key, value in arguments.items() if key != 'cookies'}
        browser = await self._resolve_browser(tool)
        context = await browser.new_context()
        try:
            await context.add_cookies(cookies)
            page = await context.new_page()
            if tool.post_auth_start_url:
                await page.goto(tool.post_auth_start_url)
            script = self._generator.generate_script(tool.steps, tool.params, is_local=(settings.storage_backend == 'local'))
            result = await self._script_runner(page, script, kwargs)
            return result
        finally:
            await context.close()

    async def _resolve_browser(self, tool):
        if self._browser_factory is None:
            raise RuntimeError('No browser factory configured for RPA MCP execution')
        browser = self._browser_factory(tool=tool)
        if hasattr(browser, '__await__'):
            browser = await browser
        return browser

    async def _default_runner(self, page, script: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {"success": True, "data": {}, "script": script, "kwargs": kwargs}
