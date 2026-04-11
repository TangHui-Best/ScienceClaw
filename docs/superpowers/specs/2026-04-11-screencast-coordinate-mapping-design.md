# Screencast Coordinate Mapping Design

## Goal

Fix local-mode screencast input drift so mouse and wheel events map exactly to the browser viewport across different monitor resolutions, DPI scales, window sizes, and `object-contain` letterboxing.

## Root Cause

The current pipeline mixes different coordinate spaces:

- Frontend pointer events are normalized against the full canvas CSS box.
- The visible screencast image may occupy only part of that box because of `object-contain`.
- Backend converts normalized coordinates using `Page.screencastFrame` metadata `deviceWidth` and `deviceHeight`.
- CDP `Input.dispatchMouseEvent` expects coordinates in main-frame viewport CSS pixels, not generic screen-sized dimensions.

This mismatch becomes more visible on external displays where screen size and browser viewport size diverge more sharply.

## Chosen Approach

Use viewport CSS pixels as the only input coordinate space.

- Backend will query `Page.getLayoutMetrics` and store `cssVisualViewport.clientWidth` and `cssVisualViewport.clientHeight` as the input dispatch basis.
- Backend `frame` payloads will include both frame bitmap size and input viewport size.
- Frontend will compute the actual displayed image rectangle inside the canvas container using contain-fit geometry.
- Frontend will convert pointer events from container CSS pixels into viewport CSS pixels before sending them.
- Shared geometry helpers will be reused by all local screencast canvas surfaces.

## Scope

Included:

- `RpaClaw/backend/rpa/screencast.py`
- `RpaClaw/backend/tests/test_rpa_screencast.py`
- `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- `RpaClaw/frontend/src/pages/rpa/TestPage.vue`
- `RpaClaw/frontend/src/components/SandboxPreview.vue`
- `RpaClaw/frontend/src/components/toolViews/BrowserToolView.vue`
- New shared frontend screencast geometry utility and tests

Not included:

- Docker/noVNC mode behavior
- Broad refactors outside local screencast rendering/input

## Data Flow

1. Backend receives a screencast frame.
2. Backend reads or refreshes viewport CSS metrics from CDP.
3. Backend sends:
   - frame bitmap width/height
   - input viewport width/height
   - existing frame metadata
4. Frontend draws the bitmap to canvas.
5. Frontend computes the contain-fit content rectangle inside the canvas element.
6. Frontend converts pointer coordinates from DOM client coordinates to bitmap-relative ratios, then to viewport CSS pixel coordinates.
7. Backend dispatches these CSS pixel coordinates directly to CDP.

## Error Handling

- If viewport metrics are unavailable, backend falls back to frame dimensions until fresh metrics are available.
- If pointer events land outside the displayed content rectangle, frontend clamps or ignores them instead of sending coordinates from the black bars.
- Geometry utilities remain pure and deterministic so failures are easy to test.

## Testing

- Backend regression tests for:
  - viewport metric selection from `Page.getLayoutMetrics`
  - direct CSS-pixel dispatch without `deviceWidth` scaling drift
- Frontend unit tests for:
  - exact mapping with matching aspect ratios
  - horizontal letterboxing
  - vertical letterboxing
  - resize scenarios

