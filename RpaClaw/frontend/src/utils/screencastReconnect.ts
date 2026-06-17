const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 5000;

export const SCREENCAST_RECONNECT_NOTICE_DELAY_MS = 1500;

export function getScreencastReconnectDelayMs(attempt: number): number {
  const normalizedAttempt = Number.isFinite(attempt)
    ? Math.max(1, Math.floor(attempt))
    : 1;
  return Math.min(INITIAL_RECONNECT_DELAY_MS * normalizedAttempt, MAX_RECONNECT_DELAY_MS);
}

export function getScreencastReconnectNoticeDelayMs({
  outageStartedAtMs,
  nowMs,
  noticeDelayMs = SCREENCAST_RECONNECT_NOTICE_DELAY_MS,
}: {
  outageStartedAtMs: number;
  nowMs: number;
  noticeDelayMs?: number;
}): number {
  if (outageStartedAtMs <= 0) return noticeDelayMs;
  return Math.max(0, noticeDelayMs - (nowMs - outageStartedAtMs));
}

export function buildScreencastReconnectMessage(contextLabel: string, reconnectDelayMs: number): string {
  return `${contextLabel}画面流暂时中断，正在尝试重连... (${reconnectDelayMs}ms)`;
}

export function isTerminalScreencastClose(code: number): boolean {
  return code === 1008 || code === 1011;
}

export function shouldShowScreencastReconnectNotice({
  shouldReconnect,
  hasPendingReconnect,
}: {
  shouldReconnect: boolean;
  hasPendingReconnect: boolean;
}): boolean {
  return shouldReconnect && hasPendingReconnect;
}
