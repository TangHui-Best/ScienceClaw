// @vitest-environment jsdom

import { createApp, nextTick, ref } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const push = vi.fn();
const get = vi.fn();
const post = vi.fn();
const deleteRequest = vi.fn();

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push }),
}));

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    delete: (...args: unknown[]) => deleteRequest(...args),
  },
}));

vi.mock('@/api/models', () => ({
  listModels: () => Promise.resolve([]),
}));

vi.mock('@/utils/sandbox', () => ({
  getBackendWsUrl: () => 'ws://localhost/rpa/screencast/session-1',
}));

vi.mock('@/components/icons/ProviderIcon.vue', () => ({
  default: {
    name: 'ProviderIconStub',
    template: '<span />',
  },
}));

vi.mock('@/components/rpa/RpaFlowGuide.vue', () => ({
  default: {
    name: 'RpaFlowGuideStub',
    props: ['recordedStepCount'],
    template: '<div data-testid="flow-guide">{{ recordedStepCount }}</div>',
  },
}));

vi.mock('@/components/rpa/RpaStepTimeline.vue', () => ({
  default: {
    name: 'RpaStepTimelineStub',
    props: ['steps'],
    emits: ['delete-step'],
    template: `
      <div data-testid="step-timeline">
        <div
          v-for="(step, index) in steps"
          :key="step.id"
          data-testid="timeline-step"
        >
          <span>{{ step.title }} {{ step.description }}</span>
          <button
            type="button"
            data-testid="delete-step"
            @click="$emit('delete-step', { step, index })"
          >
            Delete
          </button>
        </div>
      </div>
    `,
  },
}));

class MockWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances: MockWebSocket[] = [];
  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor() {
    MockWebSocket.instances.push(this);
    setTimeout(() => this.onopen?.(), 0);
  }

  send() {}

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

const mountRecorderPage = async () => {
  const { default: RecorderPage } = await import('./RecorderPage.vue');
  const root = document.createElement('div');
  document.body.appendChild(root);

  const recorder = ref<any>(null);
  const app = createApp({
    components: { RecorderPage },
    setup() {
      return { recorder };
    },
    template: '<RecorderPage ref="recorder" />',
  });
  app.mount(root);
  await flushAsyncUpdates();

  return { app, root, recorder };
};

const mockStartSession = () => {
  post.mockImplementation((url: string) => {
    if (url === '/rpa/session/start') {
      return Promise.resolve({
        data: {
          status: 'success',
          session: { id: 'session-1' },
        },
      });
    }
    return Promise.resolve({ data: {} });
  });
};

const mockChatSse = (chunks: string[]) => {
  const encoder = new TextEncoder();
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    body: {
      getReader: () => {
        let index = 0;
        return {
          read: () => {
            if (index >= chunks.length) {
              return Promise.resolve({ done: true, value: undefined });
            }
            const value = encoder.encode(chunks[index]);
            index += 1;
            return Promise.resolve({ done: false, value });
          },
        };
      },
    },
  })));
};

describe('RecorderPage trace timeline convergence', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', MockWebSocket);
    document.body.innerHTML = '';
    get.mockReset();
    post.mockReset();
    deleteRequest.mockReset();
    push.mockReset();
    MockWebSocket.instances = [];
    vi.stubGlobal('fetch', vi.fn());
    mockStartSession();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it('polls display timeline from projection and ignores legacy poison sources', async () => {
    get.mockResolvedValue({
      data: {
        session: {
          timeline: [
            {
              kind: 'trace',
              trace_id: 'trace-valid',
              action: 'click',
              title: 'Click valid target',
              summary: 'Valid target',
            },
          ],
          steps: [{ description: 'DO_NOT_USE_LEGACY step' }],
          recorded_actions: [{ description: 'DO_NOT_USE_LEGACY action' }],
          recording_diagnostics: [{ failure_reason: 'DO_NOT_USE_LEGACY diagnostic' }],
        },
      },
    });

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();

    expect(root.textContent).toContain('Click valid target');
    expect(root.textContent).not.toContain('DO_NOT_USE_LEGACY');

    app.unmount();
  });

  it('does not fall back to session steps or recorded actions when projection is absent', async () => {
    get.mockResolvedValue({
      data: {
        session: {
          steps: [{ description: 'DO_NOT_USE_LEGACY step' }],
          recorded_actions: [{ description: 'DO_NOT_USE_LEGACY action' }],
          recording_diagnostics: [{ failure_reason: 'DO_NOT_USE_LEGACY diagnostic' }],
        },
      },
    });

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();

    expect(root.textContent).not.toContain('DO_NOT_USE_LEGACY');

    app.unmount();
  });

  it('deletes projected trace items by trace id and never calls step endpoints', async () => {
    get.mockResolvedValue({
      data: {
        session: {
          timeline: [
            {
              kind: 'trace',
              trace_id: 'trace-delete-me',
              action: 'click',
              title: 'Click removable target',
              summary: 'Removable target',
            },
          ],
        },
      },
    });
    deleteRequest.mockResolvedValue({ data: {} });

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();
    deleteRequest.mockClear();

    const buttons = root.querySelectorAll<HTMLButtonElement>('[data-testid="delete-step"]');
    buttons[1]?.click();
    await flushAsyncUpdates();

    expect(deleteRequest).toHaveBeenCalledWith('/rpa/session/session-1/trace/trace-delete-me');
    expect(deleteRequest.mock.calls.some(([url]) => String(url).includes('/step/'))).toBe(false);

    app.unmount();
  });

  it('does not infer completed trace count from visible timeline length', async () => {
    get.mockResolvedValue({
      data: {
        session: {
          timeline: [
            {
              kind: 'trace',
              trace_id: 'trace-one',
              action: 'click',
              title: 'Click first target',
              summary: 'First target',
            },
            {
              kind: 'trace',
              trace_id: 'trace-two',
              action: 'click',
              title: 'Click second target',
              summary: 'Second target',
            },
          ],
        },
      },
    });

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'record task';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();
    mockChatSse([
      'event: agent_done\ndata: {"message":"Task completed","total_steps":999}\n\n',
    ]);

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    expect(root.textContent).toContain('本次记录 0 个可回放步骤');
    expect(root.textContent).not.toContain('本次记录 2 个可回放步骤');
    expect(root.textContent).not.toContain('999');

    app.unmount();
  });

  it('does not infer completed trace count from accepted traces when trace_count is absent', async () => {
    get.mockResolvedValue({
      data: {
        session: {
          traces: [
            { trace_id: 'trace-one', trace_type: 'manual_action', action: 'click' },
            { trace_id: 'trace-two', trace_type: 'manual_action', action: 'click' },
          ],
        },
      },
    });

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'record task';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    mockChatSse([
      'event: agent_done\ndata: {"message":"Task completed","total_steps":999}\n\n',
    ]);

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    expect(root.textContent).toContain('本次记录 0 个可回放步骤');
    expect(root.textContent).not.toContain('本次记录 2 个可回放步骤');
    expect(root.textContent).not.toContain('999');

    app.unmount();
  });

  it('includes pending region id in the next assistant chat request', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    mockChatSse([
      'event: agent_done\ndata: {"message":"Task completed","trace_count":1}\n\n',
    ]);

    const { app, root, recorder } = await mountRecorderPage();
    recorder.value.setPendingRegion({
      regionId: 'region-1',
      kind: 'page_region',
      summary: 'Search results area',
    });
    await flushAsyncUpdates();

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'extract the selected result';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, requestInit] = fetchMock.mock.calls[0];
    expect(JSON.parse(String((requestInit as RequestInit).body))).toMatchObject({
      message: 'extract the selected result',
      mode: 'trace_first',
      region_id: 'region-1',
    });
    expect(root.textContent).toContain('Search results area');

    app.unmount();
  });

  it('keeps pending region and shows a prompt when sending empty text', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });

    const { app, root, recorder } = await mountRecorderPage();
    recorder.value.setPendingRegion({
      regionId: 'region-2',
      kind: 'page_region',
      summary: 'Login form area',
    });
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    expect(fetch).not.toHaveBeenCalled();
    expect(root.textContent).toContain('Type what to do with the selected region');
    expect(root.textContent).toContain('Login form area');

    app.unmount();
  });
});
