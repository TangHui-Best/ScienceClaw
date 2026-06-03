import asyncio
import json as _json
import re
import sys
import time
from playwright.async_api import async_playwright


def _resolve_result_ref(results, ref):
    current = results
    for segment in str(ref).split('.'):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit():
            current = current[int(segment)]
            continue
        raise KeyError(ref)
    return current

def _resolve_first_result_ref(results, refs):
    last_error = None
    for ref in refs:
        try:
            return _resolve_result_ref(results, ref)
        except KeyError as exc:
            last_error = exc
    raise last_error or KeyError(refs[0] if refs else '')

def _validate_non_empty_records(key, value):
    if not isinstance(value, list) or not value:
        raise RuntimeError(f'AI trace output {key} is empty')

async def _download_from_export_task(page, kwargs, results, download_key, *, table_heading='', row_selector='tbody tr', action_selector='a', row_index=0, timeout_ms=60000):
    import os as _os
    _dl_dir = kwargs.get('_downloads_dir', '.')
    _os.makedirs(_dl_dir, exist_ok=True)
    deadline = time.perf_counter() + (timeout_ms / 1000)
    last_error = None
    while time.perf_counter() < deadline:
        try:
            if table_heading:
                heading = page.get_by_text(table_heading, exact=True).first
                if await heading.count():
                    rows = heading.locator("xpath=following::table[.//tbody/tr][1]//tbody/tr")
                else:
                    rows = page.locator(row_selector)
            else:
                rows = page.locator(row_selector)
            if await rows.count() <= row_index:
                await page.wait_for_timeout(1000)
                continue
            row = rows.nth(row_index)
            action = row.locator(action_selector).first
            if not await action.count() or not await action.is_visible() or not await action.is_enabled():
                await page.wait_for_timeout(1000)
                continue
            async with page.expect_download(timeout=3000) as _dl_info:
                await action.click()
            _dl = await _dl_info.value
            _dl_dest = _os.path.join(_dl_dir, _dl.suggested_filename)
            await _dl.save_as(_dl_dest)
            return {"filename": _dl.suggested_filename, "path": _dl_dest}
        except Exception as exc:
            last_error = exc
            await page.wait_for_timeout(1000)
    detail = f': {last_error}' if last_error else ''
    raise RuntimeError(f'Export task download did not produce a file within {timeout_ms}ms{detail}')

def _trace_page_url(page):
    try:
        return str(getattr(page, 'url', '') or '')
    except Exception:
        return ''

def _trace_emit(logger, event, index, description, page, started_at=None, error=None):
    if not callable(logger):
        return
    prefix = {'START': 'TRACE_START', 'DONE': 'TRACE_DONE', 'ERROR': 'TRACE_ERROR'}.get(event, f'TRACE_{event}')
    parts = [f'{prefix} {index}: {description}']
    if started_at is not None:
        parts.append(f'duration_ms={(time.perf_counter() - started_at) * 1000:.1f}')
    page_url = _trace_page_url(page)
    if page_url:
        parts.append(f'url={page_url}')
    if error is not None:
        message = str(error).replace('\n', ' ')[:300]
        parts.append(f'error={type(error).__name__}: {message}')
    try:
        logger(' | '.join(parts))
    except Exception:
        pass

def _trace_start(logger, index, description, page):
    started_at = time.perf_counter()
    _trace_emit(logger, 'START', index, description, page)
    return started_at

def _trace_done(logger, index, description, page, started_at):
    _trace_emit(logger, 'DONE', index, description, page, started_at)

def _trace_error(logger, index, description, page, started_at, error):
    _trace_emit(logger, 'ERROR', index, description, page, started_at, error)

def _normalize_runtime_ai_payload(payload, page_url=''):
    if isinstance(payload, dict) and len(payload) == 1:
        only_value = next(iter(payload.values()))
        if isinstance(only_value, dict):
            payload = only_value
    if isinstance(payload, str):
        payload = {'value': payload}
    if not isinstance(payload, dict):
        payload = {'value': payload}
    value = payload.get('value')
    if 'url' not in payload and isinstance(value, str) and value.startswith(('http://', 'https://')):
        payload['url'] = value
    if 'url' not in payload and page_url:
        payload['url'] = page_url
    return payload

async def _extract_display_field_value(field):
    value_selectors = [
        '.aui-input-display-only__content',
        '.aui-numeric-display-only__value',
        '.aui-range-editor-display-only',
        '.aui-input-display-only',
        '.no-value',
        'input',
        'textarea',
        'select',
    ]
    for selector in value_selectors:
        candidate = field.locator(selector).first
        try:
            if not await candidate.count():
                continue
            tag_name = await candidate.evaluate('el => el.tagName.toLowerCase()')
            if tag_name in ('input', 'textarea', 'select'):
                value = await candidate.input_value()
            else:
                value = await candidate.inner_text()
            value = str(value or '').strip()
            if value and value != '-':
                return value
        except Exception:
            continue
    return ''

async def _extract_bounded_section_text(heading):
    try:
        if not await heading.count():
            return ''
        handle = await heading.element_handle()
        if handle is None:
            return ''
        value = await handle.evaluate("""
node => {
  const blockTags = new Set(['P', 'DIV', 'SPAN', 'LI', 'DD']);
  const stopTags = new Set(['H1', 'H2', 'H3', 'H4', 'H5', 'H6']);
  const excludedTags = new Set(['A', 'BUTTON', 'NAV', 'UL', 'OL', 'FORM', 'INPUT', 'TEXTAREA', 'SELECT']);
  const clean = value => String(value || '').replace(/\\s+/g, ' ').trim();
  const visible = el => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 1 && rect.height > 1;
  };
  const usable = el => {
    if (!el || excludedTags.has(el.tagName) || stopTags.has(el.tagName) || !visible(el)) return false;
    if (!blockTags.has(el.tagName)) return false;
    const text = clean(el.innerText || el.textContent);
    if (!text) return false;
    const linkText = clean(Array.from(el.querySelectorAll('a')).map(a => a.innerText || a.textContent).join(' '));
    return !linkText || linkText.length < text.length;
  };
  const root = node.parentElement;
  if (!root) return '';
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  let seenHeading = false;
  while (walker.nextNode()) {
    const el = walker.currentNode;
    if (el === node) { seenHeading = true; continue; }
    if (!seenHeading) continue;
    if (stopTags.has(el.tagName)) break;
    if (usable(el)) return clean(el.innerText || el.textContent);
  }
  return '';
}
""")
        return str(value or '').strip()
    except Exception:
        return ''

async def _execute_runtime_ai_instruction(page, results, kwargs, instruction, output_key):
    from backend.rpa.recording_runtime_agent import RecordingRuntimeAgent
    agent = RecordingRuntimeAgent(model_config=_runtime_ai_model_config(kwargs))
    outcome = await agent.run(page=page, instruction=instruction, runtime_results=results)
    if not outcome.success:
        detail = '; '.join(str(item.message) for item in outcome.diagnostics) or outcome.message
        raise RuntimeError(f'Runtime semantic instruction failed: {detail}')
    payload = outcome.output
    if isinstance(payload, dict) and output_key in payload and isinstance(payload.get(output_key), (dict, list, str)):
        payload = payload.get(output_key)
    payload = _normalize_runtime_ai_payload(payload, getattr(page, 'url', ''))
    if outcome.output_key and outcome.output_key not in results:
        results[outcome.output_key] = payload
    if output_key:
        results[output_key] = payload
    return payload

def _runtime_ai_model_config(kwargs):
    runtime_context = kwargs.get('_runtime_context') if isinstance(kwargs, dict) else None
    runtime_ai = runtime_context.get('runtime_ai') if isinstance(runtime_context, dict) else None
    model_config = runtime_ai.get('model_config') if isinstance(runtime_ai, dict) else None
    return model_config or kwargs.get('_model_config')

async def _activate_recorded_page(page, kwargs, tab_id=''):
    activator = kwargs.get('_activate_recorded_page') if isinstance(kwargs, dict) else None
    if callable(activator):
        await activator(page, tab_id)

async def _ensure_recorded_tab(tabs, current_page, kwargs, tab_id, recorded_url='', require_recorded_url=False):
    if tab_id in tabs:
        page = tabs[tab_id]
    else:
        if require_recorded_url and not recorded_url:
            raise RuntimeError(f'Recorded tab {tab_id} is missing recorded URL; cannot materialize replay page safely')
        page = await current_page.context.new_page()
        tabs[tab_id] = page
        if recorded_url:
            await page.goto(recorded_url, wait_until='domcontentloaded')
    await page.bring_to_front()
    await _activate_recorded_page(page, kwargs, tab_id)
    return page

async def _resolve_recorded_frame(page_or_frame, *, url_contains='', timeout_ms=60000):
    deadline = time.perf_counter() + (timeout_ms / 1000)
    last_urls = []
    while time.perf_counter() < deadline:
        frames = list(getattr(page_or_frame, 'frames', None) or getattr(page_or_frame, 'child_frames', []) or [])
        last_urls = []
        for frame in frames:
            frame_url = str(getattr(frame, 'url', '') or '')
            if frame_url:
                last_urls.append(frame_url)
            if url_contains and url_contains in frame_url:
                return frame
        await asyncio.sleep(0.5)
    observed = ', '.join(last_urls[:5])
    detail = f' Observed frames: {observed}' if observed else ''
    raise RuntimeError(f'Recorded iframe context was not found for url_contains={url_contains!r}.{detail}')

async def execute_skill(page, **kwargs):
    """Auto-generated skill from RPA trace recording."""
    _results = {}
    current_page = page
    tabs = {"4cd94903-8282-44f6-aebd-9cdbf30159bc": page}
    _trace_logger = kwargs.get('_on_log')

    _trace_started_at = _trace_start(_trace_logger, 0, '导航到 https://github.com/trending', current_page)
    try:

        # trace 0: 导航到 https://github.com/trending
        _target_url = 'https://github.com/trending'
        await current_page.goto(_target_url, wait_until='domcontentloaded')
        await current_page.wait_for_load_state('domcontentloaded')
    except Exception as _trace_exc:
        _trace_error(_trace_logger, 0, '导航到 https://github.com/trending', current_page, _trace_started_at, _trace_exc)
        raise
    else:
        _trace_done(_trace_logger, 0, '导航到 https://github.com/trending', current_page, _trace_started_at)

    _trace_started_at = _trace_start(_trace_logger, 1, 'Click the project most relevant to finance (MoneyPrinterTurbo)', current_page)
    try:

        # trace 1: runtime semantic instruction
        _result = await _execute_runtime_ai_instruction(current_page, _results, kwargs, '点击和金融最相关的项目', 'ai_result_1')
    except Exception as _trace_exc:
        _trace_error(_trace_logger, 1, 'Click the project most relevant to finance (MoneyPrinterTurbo)', current_page, _trace_started_at, _trace_exc)
        raise
    else:
        _trace_done(_trace_logger, 1, 'Click the project most relevant to finance (MoneyPrinterTurbo)', current_page, _trace_started_at)

    _trace_started_at = _trace_start(_trace_logger, 2, 'Extract the content of the About section', current_page)
    try:

        # trace 2: Extract the content of the About section
        _result = ''
        _heading = current_page.get_by_text('About').first
        _result = await _extract_bounded_section_text(_heading)
        _results['about_content'] = _result
    except Exception as _trace_exc:
        _trace_error(_trace_logger, 2, 'Extract the content of the About section', current_page, _trace_started_at, _trace_exc)
        raise
    else:
        _trace_done(_trace_logger, 2, 'Extract the content of the About section', current_page, _trace_started_at)

    _trace_started_at = _trace_start(_trace_logger, 3, '点击 link("Issues 10") 并跳转页面', current_page)
    try:

        # trace 3: 点击 link("Issues 10") 并跳转页面
        async with current_page.expect_navigation(wait_until='domcontentloaded'):
            await current_page.get_by_role('link', name='Issues 10').click()
        await current_page.wait_for_load_state('domcontentloaded')
    except Exception as _trace_exc:
        _trace_error(_trace_logger, 3, '点击 link("Issues 10") 并跳转页面', current_page, _trace_started_at, _trace_exc)
        raise
    else:
        _trace_done(_trace_logger, 3, '点击 link("Issues 10") 并跳转页面', current_page, _trace_started_at)

    _trace_started_at = _trace_start(_trace_logger, 4, 'Extract titles of the first 10 issues from the list', current_page)
    try:

        # trace 4: runtime semantic instruction
        _result = await _execute_runtime_ai_instruction(current_page, _results, kwargs, '获取前10项Issues的标题信息', 'issue_titles')
    except Exception as _trace_exc:
        _trace_error(_trace_logger, 4, 'Extract titles of the first 10 issues from the list', current_page, _trace_started_at, _trace_exc)
        raise
    else:
        _trace_done(_trace_logger, 4, 'Extract titles of the first 10 issues from the list', current_page, _trace_started_at)
    return _results


def _parse_cli_value(key, value):
    if key in {"_runtime_context", "_model_config"}:
        try:
            return _json.loads(value)
        except Exception:
            return value
    return value


async def main():
    kwargs = {}
    for arg in sys.argv[1:]:
        if arg.startswith("--") and "=" in arg:
            k, v = arg[2:].split("=", 1)
            kwargs[k] = _parse_cli_value(k, v)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(**{'headless': False, 'args': ['--disable-cache', '--activate-on-launch', '--disable-features=MediaRouter,WebUsb,WebHid,Serial,Discovery,NetworkPrediction', '--disable-background-networking', '--disable-client-side-phishing-detection', '--disable-features=IsolateOrigins,site-per-process', '--disable-web-security', '--allow-running-insecure-content', '--disable-features=PermissionsAPI']})
    context = await browser.new_context(**{'no_viewport': True, 'accept_downloads': True, 'ignore_https_errors': True})
    page = await context.new_page()
    page.set_default_timeout(60000)
    page.set_default_navigation_timeout(60000)
    try:
        result = await execute_skill(page, **kwargs)
        if result:
            print("SKILL_DATA:" + _json.dumps(result, ensure_ascii=False, default=str))
        print("SKILL_SUCCESS")
    except Exception as exc:
        print(f"SKILL_ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await context.close()
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
