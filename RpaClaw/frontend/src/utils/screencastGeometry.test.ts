import { describe, expect, it } from 'vitest';
import {
  computeContainRect,
  getFrameSizeFromMetadata,
  mapClientPointToViewportPoint,
} from './screencastGeometry';

describe('computeContainRect', () => {
  it('prefers loaded bitmap dimensions over metadata frame dimensions for rendering', () => {
    expect(
      getFrameSizeFromMetadata(
        { frameWidth: 1920, frameHeight: 1080 },
        { width: 1280, height: 720 },
      ),
    ).toEqual({
      width: 1280,
      height: 720,
    });
  });

  it('returns the full container when aspect ratios match', () => {
    expect(
      computeContainRect(
        { width: 800, height: 600 },
        { width: 1600, height: 1200 },
      ),
    ).toEqual({
      left: 0,
      top: 0,
      width: 800,
      height: 600,
    });
  });

  it('computes left and right letterboxing for narrower content', () => {
    expect(
      computeContainRect(
        { width: 1200, height: 600 },
        { width: 800, height: 600 },
      ),
    ).toEqual({
      left: 200,
      top: 0,
      width: 800,
      height: 600,
    });
  });

  it('computes top and bottom letterboxing for wider content', () => {
    expect(
      computeContainRect(
        { width: 800, height: 800 },
        { width: 1600, height: 900 },
      ),
    ).toEqual({
      left: 0,
      top: 175,
      width: 800,
      height: 450,
    });
  });
});

describe('mapClientPointToViewportPoint', () => {
  it('maps the center point for an exact-fit frame', () => {
    expect(
      mapClientPointToViewportPoint({
        clientX: 410,
        clientY: 320,
        containerRect: { left: 10, top: 20, width: 800, height: 600 },
        frameSize: { width: 1600, height: 1200 },
        inputSize: { width: 800, height: 600 },
      }),
    ).toEqual({ x: 400, y: 300 });
  });

  it('ignores points that land inside horizontal black bars', () => {
    expect(
      mapClientPointToViewportPoint({
        clientX: 100,
        clientY: 300,
        containerRect: { left: 0, top: 0, width: 1200, height: 600 },
        frameSize: { width: 800, height: 600 },
        inputSize: { width: 800, height: 600 },
      }),
    ).toBeNull();
  });

  it('maps points inside a vertically letterboxed frame', () => {
    expect(
      mapClientPointToViewportPoint({
        clientX: 400,
        clientY: 400,
        containerRect: { left: 0, top: 0, width: 800, height: 800 },
        frameSize: { width: 1600, height: 900 },
        inputSize: { width: 800, height: 600 },
      }),
    ).toEqual({ x: 400, y: 300 });
  });

  it('recomputes correctly for resized containers', () => {
    expect(
      mapClientPointToViewportPoint({
        clientX: 300,
        clientY: 200,
        containerRect: { left: 0, top: 0, width: 600, height: 400 },
        frameSize: { width: 1600, height: 900 },
        inputSize: { width: 800, height: 450 },
      }),
    ).toEqual({ x: 400, y: 225 });
  });
});
