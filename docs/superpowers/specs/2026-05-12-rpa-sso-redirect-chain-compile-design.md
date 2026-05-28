> Legacy spec。此文档保留在 `docs/superpowers/specs/` 作为历史设计材料，当前归属 `F001` 链接引用，不是 Harness artifact。

# RPA SSO Redirect Chain Compile Design

## Vision Anchor

Trace-first recording should preserve browser facts during SSO and SPA redirects, but replay should execute only the user's intended operations. Automatic same-tab navigation continuations after a user click are evidence for the click outcome, not independent user steps.

## Problem

In SSO flows, a click can produce a chain such as:

```text
click "使用 SSO 登录"
-> login.html?code=...&state=...
-> https://app.example/
-> https://app.example/#/
-> https://app.example/#/ha/cluster
```

The current compiler replays each recorded navigation as a separate `goto`. This can race the application while it is exchanging the authorization code and writing login state. It can also replay one-time callback URLs or malformed hash routes such as `#/#/ha/cluster`.

## Scope

- Fold same-tab automatic navigation traces that immediately follow a navigation-producing user action.
- Use the folded final URL as a post-click wait target.
- Avoid replaying one-time authentication callback URLs.
- Preserve ordinary manual navigation, popup/download handling, and menu clicks.
- Fix hash route generation so absolute recorded SPA URLs are not rebuilt from the current URL.

## Non-goals

- Do not add site-specific Huawei rules.
- Do not introduce global fixed sleeps.
- Do not change recording-time trace capture as the primary fix.
- Do not require a stable page element when the final URL is the reliable completion signal.

## Design

Before rendering traces, the compiler builds a replay plan from accepted traces. A navigation trace is treated as redirect continuation when it:

- is same-tab as the preceding navigation-producing manual action,
- has no locator candidates,
- has no user action sequence,
- occurs before the next real user action,
- and is part of a short automatic chain whose final URL is the page where the next user action happens, or otherwise is the last non-callback URL in the chain.

The preceding `navigate_click` or `navigate_press` renders its normal interaction and then waits for the folded final URL. Folded navigation traces render no standalone `goto`.

Sensitive callback URLs containing `code`, `state`, `token`, `ticket`, or `SAMLResponse` are never chosen as standalone replay targets when a later non-callback URL exists in the same continuation chain.

Hash-route URLs are rendered as absolute recorded URLs unless a true dataflow expression is available. The compiler must not derive `https://host/#/#/path` from a current `https://host/#/` URL.

## Acceptance Criteria

- SSO flow compiles to click plus `wait_for_url("https://oseasy.his.huawei.com/#/ha/cluster", ...)`.
- SSO intermediate redirects after the click do not compile to standalone `goto`.
- Generated code does not contain `login.html?code=`.
- Generated code does not contain `#/#/ha/cluster`.
- Ordinary standalone manual navigation still compiles to `goto`.
- Popup and download side-effect rendering stays unchanged.

## Verification

Add targeted unit tests for:

- redirect continuation folding after `navigate_click`,
- preserving ordinary standalone manual navigation,
- avoiding malformed hash-route concatenation.
