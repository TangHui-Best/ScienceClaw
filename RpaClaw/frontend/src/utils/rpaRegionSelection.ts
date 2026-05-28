import type { ScreencastSize } from './screencastGeometry';

export interface ViewportPoint {
  x: number;
  y: number;
}

export interface RegionSelectionRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface RegionAnalyzePayload {
  tab_id: string;
  rect: RegionSelectionRect;
  viewport: ScreencastSize;
}

export interface ElementBoundsPayload {
  tab_id: string;
  point: ViewportPoint;
  viewport: ScreencastSize;
}

export interface ElementBoundsResponse {
  rect: RegionSelectionRect | null;
  tag?: string;
  role?: string;
  name?: string;
  text?: string;
  warnings?: string[];
}

export interface RegionAnalyzeResponse {
  region_id: string;
  summary: string;
  inferred_kind: string;
  evidence?: Record<string, unknown>;
}

export interface PendingRegionAttachment {
  payload: RegionAnalyzePayload;
  response: RegionAnalyzeResponse;
  summary: string;
  inferredKind: string;
}

export const MIN_REGION_SIZE = 8;
export const CLICK_REGION_SELECTION_THRESHOLD = 6;

export const normalizeSelectionRect = (
  start: ViewportPoint,
  end: ViewportPoint,
): RegionSelectionRect => {
  const x = Math.min(start.x, end.x);
  const y = Math.min(start.y, end.y);

  return {
    x,
    y,
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  };
};

export const isUsableRegionRect = (rect: RegionSelectionRect): boolean =>
  rect.width >= MIN_REGION_SIZE && rect.height >= MIN_REGION_SIZE;

export const isClickLikeRegionSelection = (
  start: ViewportPoint,
  end: ViewportPoint,
): boolean =>
  Math.abs(end.x - start.x) <= CLICK_REGION_SELECTION_THRESHOLD &&
  Math.abs(end.y - start.y) <= CLICK_REGION_SELECTION_THRESHOLD;

export const buildRegionAnalyzePayload = ({
  tabId,
  start,
  end,
  inputSize,
}: {
  tabId: string;
  start: ViewportPoint;
  end: ViewportPoint;
  inputSize: ScreencastSize;
}): RegionAnalyzePayload => ({
  tab_id: tabId,
  rect: normalizeSelectionRect(start, end),
  viewport: inputSize,
});

export const buildElementBoundsPayload = ({
  tabId,
  point,
  inputSize,
}: {
  tabId: string;
  point: ViewportPoint;
  inputSize: ScreencastSize;
}): ElementBoundsPayload => ({
  tab_id: tabId,
  point,
  viewport: inputSize,
});

export const buildElementRegionAnalyzePayload = ({
  tabId,
  rect,
  inputSize,
}: {
  tabId: string;
  rect: RegionSelectionRect;
  inputSize: ScreencastSize;
}): RegionAnalyzePayload => ({
  tab_id: tabId,
  rect,
  viewport: inputSize,
});

export const formatElementBoundsSummary = (response: ElementBoundsResponse): string => {
  const name = response.name?.trim() || response.text?.trim() || '';
  const tag = response.tag?.trim() || '';
  if (name && tag) return `${name} (${tag})`;
  return name || tag || '';
};

export const formatRegionAttachmentSummary = (response: RegionAnalyzeResponse): string => {
  const summary = response.summary.trim();
  return summary && summary.length > 0 ? summary : '已选择页面区域';
};

export const regionKindLabel = (kind: string | undefined): string => {
  switch (kind) {
    case 'table':
    case 'table_region':
      return '表格候选';
    case 'list':
    case 'list_region':
      return '列表候选';
    case 'single_value':
    case 'single_value_region':
      return '单值候选';
    case 'button':
    case 'button_region':
      return '按钮候选';
    default:
      return '区域候选';
  }
};
