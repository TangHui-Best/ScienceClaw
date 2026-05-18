from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .frame_selectors import build_frame_path


REGION_COLLECTOR_JS = """
(rectArg) => {
  const warnings = [];
  const MAX_ELEMENTS = 40;
  const MAX_TEXT = 40;

  function norm(value) {
    return String(value || '').replace(/\\s+/g, ' ').trim();
  }

  function cssEsc(value) {
    try {
      return CSS.escape(String(value));
    } catch (error) {
      return String(value).replace(/([\\\\"'\\[\\](){}|^$.*+?])/g, '\\\\$1');
    }
  }

  function rectFromDomRect(value) {
    return {
      x: Number(value.x || value.left || 0),
      y: Number(value.y || value.top || 0),
      width: Number(value.width || 0),
      height: Number(value.height || 0)
    };
  }

  function right(rect) {
    return rect.x + rect.width;
  }

  function bottom(rect) {
    return rect.y + rect.height;
  }

  function intersectionArea(a, b) {
    const width = Math.max(0, Math.min(right(a), right(b)) - Math.max(a.x, b.x));
    const height = Math.max(0, Math.min(bottom(a), bottom(b)) - Math.max(a.y, b.y));
    return width * height;
  }

  function visible(el, rect) {
    if (!el || !el.tagName || rect.width <= 0 || rect.height <= 0) return false;
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none';
  }

  function roleOf(el) {
    const explicit = el.getAttribute && el.getAttribute('role');
    if (explicit) return explicit;
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'button') return 'button';
    if (tag === 'a' && el.getAttribute('href')) return 'link';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'submit' || type === 'button') return 'button';
      return 'textbox';
    }
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'combobox';
    if (tag === 'table') return 'table';
    return '';
  }

  function nameOf(el) {
    if (!el || !el.getAttribute) return '';
    return norm(
      el.getAttribute('aria-label') ||
      el.getAttribute('title') ||
      el.getAttribute('alt') ||
      el.getAttribute('placeholder') ||
      el.textContent ||
      el.getAttribute('value') ||
      ''
    ).slice(0, 160);
  }

  function cssFallback(el) {
    const parts = [];
    let cur = el;
    while (cur && cur !== document.body && cur !== document.documentElement && parts.length < 5) {
      let seg = cur.tagName.toLowerCase();
      if (cur.id) {
        parts.unshift('#' + cssEsc(cur.id));
        break;
      }
      if (cur.parentElement) {
        const siblings = Array.from(cur.parentElement.children).filter(child => child.tagName === cur.tagName);
        if (siblings.length > 1) seg += ':nth-of-type(' + (siblings.indexOf(cur) + 1) + ')';
      }
      parts.unshift(seg);
      cur = cur.parentElement;
    }
    return parts.join(' > ') || (el && el.tagName ? el.tagName.toLowerCase() : '');
  }

  function fallbackLocatorCandidates(el) {
    if (!el || !el.tagName) return [];
    const candidates = [];
    const role = roleOf(el);
    const name = nameOf(el);
    if (role) {
      candidates.push({
        kind: 'role',
        locator: {method: 'role', role, name},
        playwright_locator: name ? `page.get_by_role('${role}', name='${name.replace(/'/g, "\\\\'")}')` : `page.get_by_role('${role}')`
      });
    }
    const placeholder = el.getAttribute && norm(el.getAttribute('placeholder'));
    if (placeholder) {
      candidates.push({
        kind: 'placeholder',
        locator: {method: 'placeholder', value: placeholder},
        playwright_locator: `page.get_by_placeholder('${placeholder.replace(/'/g, "\\\\'")}')`
      });
    }
    const text = norm(el.textContent).slice(0, 120);
    if (text) {
      candidates.push({
        kind: 'text',
        locator: {method: 'text', value: text},
        playwright_locator: `page.get_by_text('${text.replace(/'/g, "\\\\'")}')`
      });
    }
    const title = el.getAttribute && norm(el.getAttribute('title'));
    if (title) {
      candidates.push({
        kind: 'title',
        locator: {method: 'title', value: title},
        playwright_locator: `page.get_by_title('${title.replace(/'/g, "\\\\'")}')`
      });
    }
    const selector = cssFallback(el);
    if (selector) {
      candidates.push({
        kind: 'css',
        locator: {method: 'css', value: selector},
        selector,
        playwright_locator: `page.locator('${selector.replace(/'/g, "\\\\'")}')`
      });
    }
    return candidates;
  }

  function locatorCandidates(el) {
    const recorder = globalThis.__rpaPlaywrightRecorder;
    if (recorder && typeof recorder.buildLocatorBundle === 'function') {
      try {
        const bundle = recorder.buildLocatorBundle(el);
        if (bundle && Array.isArray(bundle.candidates) && bundle.candidates.length) {
          return bundle.candidates;
        }
      } catch (error) {
        warnings.push('Playwright locator bundle failed: ' + String(error && error.message || error));
      }
    }
    return fallbackLocatorCandidates(el);
  }

  function elementRecord(el, rect) {
    return {
      tag: (el.tagName || '').toLowerCase(),
      role: roleOf(el),
      name: nameOf(el),
      text: norm(el.textContent).slice(0, 240),
      rect,
      locator_candidates: locatorCandidates(el).slice(0, 5)
    };
  }

  function nearestContainer(el) {
    let cur = el;
    while (cur && cur !== document.documentElement) {
      const tag = (cur.tagName || '').toLowerCase();
      const role = cur.getAttribute && cur.getAttribute('role');
      if (['table', 'ul', 'ol', 'form', 'section', 'article', 'main'].includes(tag)) return cur;
      if (role && ['table', 'grid', 'list', 'listbox', 'menu', 'dialog', 'region'].includes(role)) return cur;
      cur = cur.parentElement;
    }
    return el || document.body;
  }

  function findTable(elements) {
    for (const entry of elements) {
      const found = entry.el.closest && entry.el.closest('table,[role="table"],[role="grid"]');
      if (found) return found;
    }
    return null;
  }

  function tableSummary(elements) {
    const table = findTable(elements);
    if (!table) return null;
    const rows = Array.from(table.querySelectorAll('tr')).slice(0, 8);
    let headers = Array.from(table.querySelectorAll('th')).map(th => norm(th.textContent)).filter(Boolean);
    if (!headers.length && rows.length) {
      headers = Array.from(rows[0].querySelectorAll('th,td')).map(cell => norm(cell.textContent)).filter(Boolean);
    }
    const dataRows = rows
      .slice(headers.length ? 1 : 0)
      .map(row => Array.from(row.querySelectorAll('th,td')).map(cell => norm(cell.textContent)).filter(Boolean))
      .filter(row => row.length)
      .slice(0, 5);
    return {
      headers,
      sample_rows: dataRows,
      row_count: rows.length,
      locator_candidates: locatorCandidates(table).slice(0, 5)
    };
  }

  function findList(elements) {
    for (const entry of elements) {
      const found = entry.el.closest && entry.el.closest('ul,ol,[role="list"],[role="listbox"],[role="menu"]');
      if (found) return found;
    }
    return null;
  }

  function listSummary(elements) {
    const list = findList(elements);
    if (!list) return null;
    let items = Array.from(list.querySelectorAll('li,[role="listitem"],[role="option"],[role="menuitem"]'));
    let itemSelector = 'li,[role="listitem"],[role="option"],[role="menuitem"]';
    if (!items.length) {
      items = Array.from(list.children || []);
      itemSelector = ':scope > *';
    }
    return {
      item_count: items.length,
      item_selector: itemSelector,
      sample_items: items.map(item => norm(item.textContent)).filter(Boolean).slice(0, 8),
      container_locator_candidates: locatorCandidates(list).slice(0, 5)
    };
  }

  function isControl(el) {
    const tag = (el.tagName || '').toLowerCase();
    const role = roleOf(el);
    return ['button', 'a', 'input', 'select', 'textarea'].includes(tag) ||
      ['button', 'link', 'checkbox', 'radio', 'switch', 'combobox', 'textbox', 'menuitem', 'option'].includes(role) ||
      Boolean(el.isContentEditable);
  }

  function actionSummary(elements) {
    const seen = new Set();
    const controls = [];
    for (const entry of elements) {
      let control = entry.el.closest && entry.el.closest('button,a,input,select,textarea,[role="button"],[role="link"],[role="checkbox"],[role="radio"],[role="switch"],[role="combobox"],[role="textbox"],[role="menuitem"],[role="option"]');
      if (!control && isControl(entry.el)) control = entry.el;
      if (!control || seen.has(control)) continue;
      seen.add(control);
      controls.push(elementRecord(control, rectFromDomRect(control.getBoundingClientRect())));
      if (controls.length >= 20) break;
    }
    return {controls};
  }

  const selectedRect = {
    x: Number(rectArg && rectArg.x || 0),
    y: Number(rectArg && rectArg.y || 0),
    width: Number(rectArg && rectArg.width || 0),
    height: Number(rectArg && rectArg.height || 0)
  };
  const allElements = Array.from(document.body ? document.body.querySelectorAll('*') : document.querySelectorAll('*'));
  const hits = [];
  for (const el of allElements) {
    const elRect = rectFromDomRect(el.getBoundingClientRect());
    const area = intersectionArea(selectedRect, elRect);
    if (area <= 0 || !visible(el, elRect)) continue;
    hits.push({el, rect: elRect, area});
  }
  hits.sort((a, b) => b.area - a.area);

  const dominantElement = hits.length ? nearestContainer(hits[0].el) : document.body;
  const localText = [];
  const localTextSeen = new Set();
  for (const entry of hits) {
    const text = norm(entry.el.textContent);
    if (!text || localTextSeen.has(text)) continue;
    localTextSeen.add(text);
    localText.push(text.slice(0, 240));
    if (localText.length >= MAX_TEXT) break;
  }

  const dominantRect = dominantElement ? rectFromDomRect(dominantElement.getBoundingClientRect()) : {};
  return {
    rect: selectedRect,
    intersecting_elements: hits.slice(0, MAX_ELEMENTS).map(entry => elementRecord(entry.el, entry.rect)),
    local_text: localText,
    dominant_container: dominantElement ? elementRecord(dominantElement, dominantRect) : {},
    locator_candidates: dominantElement ? locatorCandidates(dominantElement).slice(0, 8) : [],
    table_summary: tableSummary(hits),
    list_summary: listSummary(hits),
    action_summary: actionSummary(hits),
    warnings
  };
}
"""


class RPARegionRect(BaseModel):
    x: float
    y: float
    width: float
    height: float

    @field_validator("width", "height")
    @classmethod
    def _positive_dimension(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("dimension must be greater than 0")
        return value


class RPARegionViewport(BaseModel):
    width: float
    height: float

    @field_validator("width", "height")
    @classmethod
    def _positive_dimension(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("dimension must be greater than 0")
        return value


class RPARegionAnalyzeRequest(BaseModel):
    tab_id: str
    rect: RPARegionRect
    viewport: RPARegionViewport


class RPARegionEvidence(BaseModel):
    url: str = ""
    title: str = ""
    frame_path: List[str] = Field(default_factory=list)
    rect: Dict[str, float] = Field(default_factory=dict)
    dominant_container: Dict[str, Any] = Field(default_factory=dict)
    intersecting_elements: List[Dict[str, Any]] = Field(default_factory=list)
    locator_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    local_text: List[str] = Field(default_factory=list)
    inferred_kind: str = "unknown"
    table_summary: Optional[Dict[str, Any]] = None
    list_summary: Optional[Dict[str, Any]] = None
    action_summary: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)


class RPARegionContext(BaseModel):
    region_id: str = Field(default_factory=lambda: f"region-{uuid4().hex}")
    session_id: str
    tab_id: str
    page_url: str = ""
    page_title: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    evidence: RPARegionEvidence

    def preview(self) -> Dict[str, Any]:
        rect = self.evidence.rect or {}
        width = int(float(rect.get("width", 0) or 0))
        height = int(float(rect.get("height", 0) or 0))
        element_count = len(self.evidence.intersecting_elements)
        return {
            "region_id": self.region_id,
            "tab_id": self.tab_id,
            "summary": f"区域 {width}x{height}，包含 {element_count} 个元素",
            "inferred_kind": self.evidence.inferred_kind,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "warnings": list(self.evidence.warnings),
        }


class RPARegionAnalyzeResponse(BaseModel):
    region_id: str
    summary: str
    inferred_kind: str = "unknown"
    evidence: RPARegionEvidence


def classify_region_evidence(raw: Dict[str, Any]) -> str:
    table_summary = raw.get("table_summary")
    if isinstance(table_summary, dict) and table_summary.get("headers"):
        return "table_region"

    list_summary = raw.get("list_summary")
    if isinstance(list_summary, dict) and int(list_summary.get("item_count") or 0) > 0:
        return "list_region"

    action_summary = raw.get("action_summary")
    if isinstance(action_summary, dict) and action_summary.get("controls"):
        return "action_region"

    local_text = raw.get("local_text")
    if isinstance(local_text, list) and any(str(item or "").strip() for item in local_text):
        return "text_region"

    return "unknown"


def _rect_dict(rect: RPARegionRect | Dict[str, Any]) -> Dict[str, float]:
    if isinstance(rect, RPARegionRect):
        return rect.model_dump()
    return {
        "x": float(rect.get("x", 0) or 0),
        "y": float(rect.get("y", 0) or 0),
        "width": float(rect.get("width", 0) or 0),
        "height": float(rect.get("height", 0) or 0),
    }


def _intersection_rect(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
    left = max(float(a.get("x", 0)), float(b.get("x", 0)))
    top = max(float(a.get("y", 0)), float(b.get("y", 0)))
    right = min(float(a.get("x", 0)) + float(a.get("width", 0)), float(b.get("x", 0)) + float(b.get("width", 0)))
    bottom = min(float(a.get("y", 0)) + float(a.get("height", 0)), float(b.get("y", 0)) + float(b.get("height", 0)))
    return {
        "x": left,
        "y": top,
        "width": max(0.0, right - left),
        "height": max(0.0, bottom - top),
    }


def _intersection_area(a: Dict[str, float], b: Dict[str, float]) -> float:
    intersection = _intersection_rect(a, b)
    return intersection["width"] * intersection["height"]


def _frame_local_rect(rect: Dict[str, float], frame_box: Dict[str, float]) -> Dict[str, float]:
    clipped = _intersection_rect(rect, frame_box)
    return {
        "x": clipped["x"] - float(frame_box.get("x", 0) or 0),
        "y": clipped["y"] - float(frame_box.get("y", 0) or 0),
        "width": clipped["width"],
        "height": clipped["height"],
    }


async def _dominant_frame_for_rect(page: Any, rect: Dict[str, float]) -> tuple[Any, Dict[str, float], List[str], List[str]]:
    warnings: List[str] = []
    frames = list(getattr(page, "frames", None) or [])
    main_frame = getattr(page, "main_frame", None)
    best_frame = None
    best_box: Dict[str, float] | None = None
    best_area = 0.0

    for frame in frames:
        if main_frame is not None and frame is main_frame:
            continue
        try:
            frame_element = await frame.frame_element()
            box = await frame_element.bounding_box()
        except Exception as exc:
            warnings.append(f"Failed to inspect frame bounds: {exc}")
            continue
        if not isinstance(box, dict):
            continue
        frame_box = _rect_dict(box)
        area = _intersection_area(rect, frame_box)
        if area > best_area:
            best_area = area
            best_frame = frame
            best_box = frame_box

    if best_frame is None or best_box is None or best_area <= 0:
        return page, rect, [], warnings

    selected_area = max(0.0, float(rect.get("width", 0) or 0) * float(rect.get("height", 0) or 0))
    main_area = max(0.0, selected_area - best_area)
    if best_area <= main_area:
        return page, rect, [], warnings

    try:
        frame_path = await build_frame_path(best_frame)
    except Exception as exc:
        warnings.append(f"Failed to build frame path: {exc}")
        frame_path = []

    return best_frame, _frame_local_rect(rect, best_box), frame_path, warnings


async def _safe_title(page: Any) -> str:
    title = getattr(page, "title", None)
    if not callable(title):
        return ""
    try:
        value = title()
        if hasattr(value, "__await__"):
            value = await value
        return str(value or "")
    except Exception:
        return ""


def _normalize_evidence(raw: Dict[str, Any], *, page: Any, rect: Dict[str, float], frame_path: List[str], warnings: List[str]) -> Dict[str, Any]:
    evidence = dict(raw or {})
    collector_warnings = evidence.get("warnings")
    if isinstance(collector_warnings, list):
        warnings = [*warnings, *[str(item) for item in collector_warnings]]
    evidence["url"] = str(getattr(page, "url", "") or evidence.get("url") or "")
    evidence["title"] = str(evidence.get("title") or "")
    evidence["frame_path"] = list(frame_path)
    evidence["rect"] = _rect_dict(evidence.get("rect") or rect)
    evidence["dominant_container"] = evidence.get("dominant_container") if isinstance(evidence.get("dominant_container"), dict) else {}
    evidence["intersecting_elements"] = evidence.get("intersecting_elements") if isinstance(evidence.get("intersecting_elements"), list) else []
    evidence["locator_candidates"] = evidence.get("locator_candidates") if isinstance(evidence.get("locator_candidates"), list) else []
    evidence["local_text"] = evidence.get("local_text") if isinstance(evidence.get("local_text"), list) else []
    evidence["table_summary"] = evidence.get("table_summary") if isinstance(evidence.get("table_summary"), dict) else None
    evidence["list_summary"] = evidence.get("list_summary") if isinstance(evidence.get("list_summary"), dict) else None
    evidence["action_summary"] = evidence.get("action_summary") if isinstance(evidence.get("action_summary"), dict) else None
    evidence["warnings"] = warnings
    evidence["inferred_kind"] = classify_region_evidence(evidence)
    return evidence


async def analyze_region_on_page(page: Any, request: RPARegionAnalyzeRequest) -> Dict[str, Any]:
    top_level_rect = request.rect.model_dump()
    target, target_rect, frame_path, warnings = await _dominant_frame_for_rect(page, top_level_rect)

    raw = await target.evaluate(REGION_COLLECTOR_JS, target_rect)
    if not isinstance(raw, dict):
        raw = {}

    evidence = _normalize_evidence(
        raw,
        page=page,
        rect=target_rect,
        frame_path=frame_path,
        warnings=warnings,
    )
    evidence["title"] = evidence.get("title") or await _safe_title(page)
    return evidence
