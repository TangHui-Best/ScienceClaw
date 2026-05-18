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

export interface RegionAnalyzeResponse {
  kind?: string;
  summary?: string;
}

export interface PendingRegionAttachment {
  payload: RegionAnalyzePayload;
  response: RegionAnalyzeResponse;
  summary: string;
}

export const MIN_REGION_SIZE = 8;

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

export const formatRegionAttachmentSummary = (response: RegionAnalyzeResponse): string => {
  const summary = response.summary?.trim();
  return summary && summary.length > 0 ? summary : '已选择页面区域';
};

export const regionKindLabel = (kind: string | undefined): string => {
  switch (kind) {
    case 'table':
      return '表格候选';
    case 'list':
      return '列表候选';
    case 'single_value':
      return '单值候选';
    case 'button':
      return '按钮候选';
    default:
      return '区域候选';
  }
};
