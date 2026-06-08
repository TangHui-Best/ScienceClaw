# AIO Native Local Smoke Evidence - 2026-06-09

本文记录一次本机 AIO native partial smoke。它证明了 AIO 执行面接入、录制 session、listener 注入、手动 trace、脚本生成、AIO runtime 下脚本测试执行、Skill 保存的主链路；它不声明完整目标完成，因为自然语言、区域选择和多 tab 仍需要逐项留证。

## 环境

- AIO sandbox container: `aio-native-manual`
- AIO image: `enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest`
- AIO port: `127.0.0.1:18090`
- Temporary Host Backend port: `127.0.0.1:8010`
- Backend env:
  - `PYTHONPATH=RpaClaw`
  - `STORAGE_BACKEND=local`
  - `AUTH_PROVIDER=none`
  - `RUNTIME_MODE=aio_native`
  - `AIO_BASE_URL=http://127.0.0.1:18090`
  - `AIO_RUNTIME_SANDBOX_ID=aio-native-manual`

## AIO browser info

`GET http://127.0.0.1:18090/v1/browser/info` returned:

```json
{
  "success": true,
  "data": {
    "cdp_url": "ws://127.0.0.1:18090/cdp/devtools/browser/3761c619-1bca-453e-a9f7-00f6772ad82e",
    "vnc_url": "http://127.0.0.1:18090/vnc/index.html",
    "viewport": {
      "width": 1280,
      "height": 1024
    }
  }
}
```

No token or sensitive header was required in this local fixed-sandbox smoke.

## API smoke sequence

### 1. Start RPA session

Request:

```http
POST http://127.0.0.1:8010/api/v1/rpa/session/start
Content-Type: application/json

{"sandbox_session_id":"aio-native-manual"}
```

Result:

- `status=success`
- `session.id=293f7e98-1feb-417a-a068-d68406783b50`
- `session.sandbox_session_id=aio-native-manual`
- `session.active_tab_id=dcd8c4eb-5c1d-42ce-8769-cf8982b1e993`

This proves Host Backend could create a recording session by connecting to the AIO browser/CDP runtime.

### 2. Navigate AIO page

Request:

```http
POST /api/v1/rpa/session/293f7e98-1feb-417a-a068-d68406783b50/navigate

{"url":"https://github.com/trending"}
```

Result:

- `status=success`
- active tab URL became `https://github.com/trending`
- tab title returned as `Trending repositories on GitHub today ... GitHub`
- accepted navigation trace was later visible in `/timeline`

Then the same session was navigated to a small `data:text/html` smoke page containing:

- textbox `Name`
- button `Click Me`
- link `Open Popup`

### 3. Listener injection and manual event capture

Using Playwright connected to AIO CDP, the same AIO page was driven with:

- `fill('#name', 'aio-native-smoke')`
- `click('#go')`
- `click('#popup')`

`GET /api/v1/rpa/session/293f7e98-1feb-417a-a068-d68406783b50/timeline` then returned accepted traces including:

- `action=navigate`, `source=manual`, `signals.tab.tab_id=dcd8c4eb-5c1d-42ce-8769-cf8982b1e993`
- `action=fill`, `value=aio-native-smoke`, locator `page.get_by_role("textbox", name="Name")`
- `action=click`, locator `page.get_by_role("button", name="Click Me")`
- `action=click`, locator `page.get_by_role("link", name="Open Popup")`

This proves the existing recorder listener JS was injected into the AIO browser page and that manual click/fill/navigation events entered the accepted timeline.

### 4. Script generation

Request:

```http
POST /api/v1/rpa/session/293f7e98-1feb-417a-a068-d68406783b50/generate

{"params":{}}
```

Result:

- `status=success`
- generated script contained `execute_skill(page, **kwargs)`
- generated trace steps included navigate, fill, and click operations derived from accepted traces

### 5. Script test execution

Request:

```http
POST /api/v1/rpa/session/293f7e98-1feb-417a-a068-d68406783b50/test

{"params":{}}
```

Result:

- `status=success`
- `result.success=true`
- `result.output=SKILL_SUCCESS`
- logs included:
  - `TRACE_DONE 0: Navigate to https://github.com/trending`
  - `TRACE_DONE 1: Navigate to data:text/html...AIO Native Smoke`
  - `TRACE_DONE 2: ... textbox("Name")`
  - `TRACE_DONE 3: ... button("Click Me")`
  - `TRACE_DONE 4: ... link("Open Popup")`

Important detail: although the returned script string includes a standalone `main()` that can launch a browser when run as a local script, the `/test` route executed `execute_skill(page, ...)` through `get_cdp_connector().get_browser(session.sandbox_session_id)`, so this API smoke exercised the AIO runtime browser path.

### 6. Skill save

Request:

```http
POST /api/v1/rpa/session/293f7e98-1feb-417a-a068-d68406783b50/save

{
  "skill_name": "aio_native_smoke_skill",
  "description": "AIO native smoke skill",
  "params": {}
}
```

Result:

- `status=success`
- `skill_name=aio_native_smoke_skill`
- local generated files were written under `Skills/aio_native_smoke_skill/`

The generated Skill directory was observed during smoke and then cleaned up because it was local output, not a governed regression asset.

### 7. Stop session

Request:

```http
POST /api/v1/rpa/session/293f7e98-1feb-417a-a068-d68406783b50/stop
```

Result:

- `status=success`
- `session.status=stopped`
- `trace_count=10`
- `diagnostic_count=0`

## Checklist status

| Goal item | Status from this smoke | Evidence |
| --- | --- | --- |
| AIO execution surface | Passed for local fixed AIO sandbox | AIO container healthy; `/v1/browser/info`; `/session/start` success |
| Recording skill starts | Passed at API level | `/session/start` returned session and active tab |
| Browser view accessible | Partially proven | AIO `vnc_url` returned; frontend visual access not rechecked in this smoke |
| Listener JS injection | Passed | CDP-driven fill/click produced accepted manual traces |
| Manual click/input/navigation | Passed | accepted navigate/fill/click traces |
| Multi tab | Not proven in this smoke | popup attempt did not produce a second registered tab |
| Natural language operations | Not run in this smoke | user had previously observed NL click/script execution; no fresh command evidence here |
| Region selection | Not run in this smoke | user had previously observed region selection eventually worked; no fresh command evidence here |
| Trace -> script generation | Passed | `/generate` returned success |
| Script execution in AIO runtime path | Passed via `/test` route | `/test` used runtime CDP browser and returned `SKILL_SUCCESS` |
| Skill save | Passed | `/save` returned `skill_name=aio_native_smoke_skill` |
| Downloads/files not blocking | Passed for no-download scenario | no download generated; main chain did not fail |
| Internal handoff | Already documented | `docs/rpa/aio-native-internal-handoff.md` and `docs/rpa/aio-native-functional-smoke-checklist.md` |

## Remaining gaps before marking the overall goal complete

1. Run and record natural-language operations in the same evidence style:
   - click
   - fill
   - navigate
   - read page information
   - accepted trace after each successful operation
2. Run and record region selection:
   - frontend selection or equivalent `region/analyze`
   - region-scoped natural-language action
   - trace containing `region_context` / `region_scope`
3. Run and record multi-tab:
   - open second tab
   - switch active tab
   - URL/title/page attribution
   - accepted events not assigned to stale tab
4. In intranet, replace fixed sandbox with real APIG lifecycle:
   - `POST /api/livefunction/sandboxes`
   - `GET /api/livefunction/sandboxes/{sandboxId}`
   - `POST /api/livefunction/sandboxes/refresh/{sandboxId}`
   - `DELETE /api/livefunction/sandboxes/{sandboxId}`
   - EKS multi-instance runtime record persistence and idempotent create
