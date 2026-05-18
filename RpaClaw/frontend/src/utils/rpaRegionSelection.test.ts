import { describe, expect, it } from 'vitest';
import {
  MIN_REGION_SIZE,
  buildRegionAnalyzePayload,
  formatRegionAttachmentSummary,
  isUsableRegionRect,
  normalizeSelectionRect,
  regionKindLabel,
} from './rpaRegionSelection';

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
    expect(formatRegionAttachmentSummary({ summary: '订单表格区域' })).toBe('订单表格区域');
  });

  it('falls back to a normal Chinese default when summary is empty', () => {
    expect(formatRegionAttachmentSummary({ summary: '' })).toBe('已选择页面区域');
    expect(formatRegionAttachmentSummary({ summary: '   ' })).toBe('已选择页面区域');
    expect(formatRegionAttachmentSummary({})).toBe('已选择页面区域');
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
});
