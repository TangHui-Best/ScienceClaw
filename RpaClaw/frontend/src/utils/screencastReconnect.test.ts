import { describe, expect, it } from 'vitest';
import {
  buildScreencastReconnectMessage,
  getScreencastReconnectDelayMs,
  getScreencastReconnectNoticeDelayMs,
  isTerminalScreencastClose,
  shouldShowScreencastReconnectNotice,
} from './screencastReconnect';

describe('screencastReconnect', () => {
  it('caps reconnect delay while keeping the first retry quick', () => {
    expect(getScreencastReconnectDelayMs(1)).toBe(1000);
    expect(getScreencastReconnectDelayMs(2)).toBe(2000);
    expect(getScreencastReconnectDelayMs(99)).toBe(5000);
  });

  it('does not expose a reconnect notice once the stream has already recovered', () => {
    expect(shouldShowScreencastReconnectNotice({
      shouldReconnect: true,
      hasPendingReconnect: false,
    })).toBe(false);

    expect(shouldShowScreencastReconnectNotice({
      shouldReconnect: true,
      hasPendingReconnect: true,
    })).toBe(true);
  });

  it('counts the notice grace period from the first disconnect', () => {
    expect(getScreencastReconnectNoticeDelayMs({
      outageStartedAtMs: 1000,
      nowMs: 1300,
    })).toBe(1200);

    expect(getScreencastReconnectNoticeDelayMs({
      outageStartedAtMs: 1000,
      nowMs: 2600,
    })).toBe(0);
  });

  it('treats policy and backend failures as terminal closes', () => {
    expect(isTerminalScreencastClose(1008)).toBe(true);
    expect(isTerminalScreencastClose(1011)).toBe(true);
    expect(isTerminalScreencastClose(1006)).toBe(false);
  });

  it('builds context-specific reconnect copy', () => {
    expect(buildScreencastReconnectMessage('录制', 2000)).toBe(
      '录制画面流暂时中断，正在尝试重连... (2000ms)',
    );
  });
});
