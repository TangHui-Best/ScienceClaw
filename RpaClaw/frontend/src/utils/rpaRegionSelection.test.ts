import { describe, expect, it } from 'vitest';
import {
  MIN_REGION_SIZE,
  buildRegionAnalyzePayload,
  buildElementBoundsPayload,
  buildElementRegionAnalyzePayload,
  formatRegionAttachmentSummary,
  isClickLikeRegionSelection,
  isUsableRegionRect,
  normalizeSelectionRect,
  regionKindLabel,
} from './rpaRegionSelection';
import type { RegionAnalyzeResponse } from './rpaRegionSelection';

describe('normalizeSelectionRect', () => {
  it('normalizes selections dragged in any direction', () => {
    const expected = { x: 20, y: 30, width: 80, height: 120 };

    expect(normalizeSelectionRect({ x: 20, y: 30 }, { x: 100, y: 150 })).toEqual(expected);
    expect(normalizeSelectionRect({ x: 100, y: 150 }, { x: 20, y: 30 })).toEqual(expected);
    expect(normalizeSelectionRect({ x: 100, y: 30 }, { x: 20, y: 150 })).toEqual(expected);
    expect(normalizeSelectionRect({ x: 20, y: 150 }, { x: 100, y: 30 })).toEqual(expected);
  });
});

describe('buildRegionAnalyzePayload', () => {
  it('builds the backend snake_case analyze payload', () => {
    expect(
      buildRegionAnalyzePayload({
        tabId: 'tab-1',
        start: { x: 120, y: 240 },
        end: { x: 40, y: 80 },
        inputSize: { width: 1440, height: 900 },
      }),
    ).toEqual({
      tab_id: 'tab-1',
      rect: {
        x: 40,
        y: 80,
        width: 80,
        height: 160,
      },
      viewport: {
        width: 1440,
        height: 900,
      },
    });
  });
});

describe('buildElementBoundsPayload', () => {
  it('builds the backend payload for resolving an element under a viewport point', () => {
    expect(
      buildElementBoundsPayload({
        tabId: 'tab-1',
        point: { x: 120, y: 240 },
        inputSize: { width: 1440, height: 900 },
      }),
    ).toEqual({
      tab_id: 'tab-1',
      point: { x: 120, y: 240 },
      viewport: {
        width: 1440,
        height: 900,
      },
    });
  });
});

describe('buildElementRegionAnalyzePayload', () => {
  it('reuses the existing region analyze payload shape with the resolved element rect', () => {
    expect(
      buildElementRegionAnalyzePayload({
        tabId: 'tab-1',
        rect: { x: 24, y: 40, width: 112, height: 32 },
        inputSize: { width: 1440, height: 900 },
      }),
    ).toEqual({
      tab_id: 'tab-1',
      rect: { x: 24, y: 40, width: 112, height: 32 },
      viewport: {
        width: 1440,
        height: 900,
      },
    });
  });
});

describe('isClickLikeRegionSelection', () => {
  it('treats tiny movement as element click and larger movement as region drag', () => {
    expect(isClickLikeRegionSelection({ x: 10, y: 20 }, { x: 12, y: 23 })).toBe(true);
    expect(isClickLikeRegionSelection({ x: 10, y: 20 }, { x: 26, y: 23 })).toBe(false);
    expect(isClickLikeRegionSelection({ x: 10, y: 20 }, { x: 12, y: 37 })).toBe(false);
  });
});

describe('isUsableRegionRect', () => {
  it('requires both dimensions to meet the minimum region size', () => {
    expect(MIN_REGION_SIZE).toBe(8);
    expect(isUsableRegionRect({ x: 0, y: 0, width: 8, height: 8 })).toBe(true);
    expect(isUsableRegionRect({ x: 0, y: 0, width: 7.99, height: 8 })).toBe(false);
    expect(isUsableRegionRect({ x: 0, y: 0, width: 8, height: 7.99 })).toBe(false);
  });
});

describe('formatRegionAttachmentSummary', () => {
  it('uses the backend summary when present', () => {
    const response: RegionAnalyzeResponse = {
      region_id: 'region-1',
      summary: '订单表格区域',
      inferred_kind: 'table_region',
      evidence: { nodeCount: 12 },
    };

    expect(formatRegionAttachmentSummary(response)).toBe('订单表格区域');
  });

  it('falls back to a normal Chinese default when summary is empty', () => {
    const response: RegionAnalyzeResponse = {
      region_id: 'region-1',
      summary: '',
      inferred_kind: 'table_region',
    };

    expect(formatRegionAttachmentSummary(response)).toBe('已选择页面区域');
    expect(formatRegionAttachmentSummary({ ...response, summary: '   ' })).toBe('已选择页面区域');
  });
});

describe('regionKindLabel', () => {
  it('formats known region kinds with normal Chinese labels', () => {
    expect(regionKindLabel('table')).toBe('表格候选');
    expect(regionKindLabel('list')).toBe('列表候选');
    expect(regionKindLabel('single_value')).toBe('单值候选');
    expect(regionKindLabel('button')).toBe('按钮候选');
    expect(regionKindLabel('unknown')).toBe('区域候选');
    expect(regionKindLabel(undefined)).toBe('区域候选');
  });

  it('uses inferred_kind from backend-shaped responses instead of a missing kind field', () => {
    const response: RegionAnalyzeResponse = {
      region_id: 'region-1',
      summary: '订单表格区域',
      inferred_kind: 'table_region',
    };

    expect(formatRegionAttachmentSummary(response)).toBe('订单表格区域');
    expect(regionKindLabel(response.inferred_kind)).toBe('表格候选');
  });
});
