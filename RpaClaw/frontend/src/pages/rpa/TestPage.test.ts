// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.fn();
const post = vi.fn();
const push = vi.fn();

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { sessionId: 'session-1' } }),
  useRouter: () => ({ push }),
}));

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}));

vi.mock('@/utils/sandbox', () => ({
  getBackendWsUrl: () => 'ws://localhost/rpa/screencast/session-1',
}));

vi.mock('@/components/rpa/RpaDiscardRecordingDialog.vue', () => ({
  default: {
    name: 'RpaDiscardRecordingDialogStub',
    template: '<div />',
  },
}));

vi.mock('@/components/rpa/RpaFlowGuide.vue', () => ({
  default: {
    name: 'RpaFlowGuideStub',
    props: ['recordedStepCount', 'diagnosticCount'],
    template: '<div data-testid="flow-guide">{{ recordedStepCount }} {{ diagnosticCount }}</div>',
  },
}));

vi.mock('@/components/rpa/RpaStepTimeline.vue', () => ({
  default: {
    name: 'RpaStepTimelineStub',
    props: ['steps', 'failedStepIndex', 'failedStepCandidates'],
    emits: ['retry-candidate'],
    template: `
      <div data-testid="step-timeline">
        <div
          v-for="step in steps"
          :key="step.id"
          data-testid="timeline-step"
        >
          {{ step.description }} {{ step.label }}
        </div>
        <button
          v-if="failedStepCandidates?.length"
          type="button"
          data-testid="retry-candidate"
          @click="$emit('retry-candidate', 0)"
        >
          Retry
        </button>
      </div>
    `,
  },
}));

class MockWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor() {
    Promise.resolve().then(() => this.onopen?.());
  }

  close() {
    this.readyState = 3;
  }
}

const flushAsyncUpdates = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await nextTick();
};

const mountTestPage = async () => {
  const { default: TestPage } = await import('./TestPage.vue');
  const root = document.createElement('div');
  document.body.appendChild(root);

  const app = createApp(TestPage);
  app.mount(root);
  await flushAsyncUpdates();

  return { app, root };
};

const mockSession = (session: any) => {
  get.mockImplementation((url: string) => {
    if (url === '/rpa/session/session-1/skill-config-draft') {
      return Promise.resolve({
        data: {
          draft: {
            skill_name: 'Trace test skill',
            description: 'Trace test',
            params: {},
          },
        },
      });
    }
    if (url === '/rpa/session/session-1') {
      return Promise.resolve({ data: { session } });
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
};

describe('TestPage trace-first failure retry', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', MockWebSocket);
    document.body.innerHTML = '';
    get.mockReset();
    post.mockReset();
    push.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it('retries failed locators by failed trace id and never calls step endpoints', async () => {
    mockSession({
      timeline: [
        {
          kind: 'trace',
          trace_id: 'trace-failed',
          action: 'click',
          title: 'Click failed target',
          summary: 'Failed target',
        },
      ],
    });
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/session-1/test') {
        return Promise.resolve({
          data: {
            result: { success: false, error: 'locator failed' },
            failed_trace_id: 'trace-failed',
            failed_step_index: 0,
            failed_step_candidates: [
              { kind: 'css', original_index: 3, locator: { method: 'css', value: '#fixed' } },
            ],
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountTestPage();
    await flushAsyncUpdates();
    post.mockClear();

    root.querySelector<HTMLButtonElement>('[data-testid="retry-candidate"]')?.click();
    await vi.waitFor(() => {
      expect(post).toHaveBeenCalledWith('/rpa/session/session-1/trace/trace-failed/locator', {
        candidate_index: 3,
      });
    });

    expect(post.mock.calls.some(([url]) => String(url).includes('/step/'))).toBe(false);

    app.unmount();
  });

  it('does not use legacy failed_step_index for locator retry when failed trace id is absent', async () => {
    mockSession({
      timeline: [
        {
          kind: 'trace',
          trace_id: 'trace-visible',
          action: 'click',
          title: 'Click visible target',
          summary: 'Visible target',
        },
      ],
    });
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/session-1/test') {
        return Promise.resolve({
          data: {
            result: { success: false, error: 'locator failed' },
            failed_step_index: 0,
            failed_step_candidates: [
              { kind: 'css', original_index: 0, locator: { method: 'css', value: '#legacy' } },
            ],
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountTestPage();
    await flushAsyncUpdates();
    post.mockClear();

    root.querySelector<HTMLButtonElement>('[data-testid="retry-candidate"]')?.click();
    await flushAsyncUpdates();

    expect(post).not.toHaveBeenCalled();
    expect(post.mock.calls.some(([url]) => String(url).includes('/step/'))).toBe(false);

    app.unmount();
  });
});
