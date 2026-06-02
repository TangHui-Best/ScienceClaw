// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '@/composables/useI18n';

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

  send = vi.fn();

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

const createDeferred = <T = unknown>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((innerResolve) => {
    resolve = innerResolve;
  });
  return { promise, resolve };
};

const mountRecorderPage = async () => {
  const { default: RecorderPage } = await import('./RecorderPage.vue');
  const root = document.createElement('div');
  document.body.appendChild(root);

  const app = createApp(RecorderPage);
  app.use(i18n);
  app.mount(root);
  await flushAsyncUpdates();

  return { app, root };
};

const dispatchSelectedRegion = (
  root: HTMLElement,
  attachment: {
    regionId: string;
    kind?: string;
    summary?: string;
  },
) => {
  const pageRoot = root.firstElementChild;
  expect(pageRoot).not.toBeNull();
  pageRoot!.dispatchEvent(new CustomEvent('rpa-region-selected', {
    bubbles: true,
    detail: attachment,
  }));
};

const getCanvas = (root: HTMLElement) => {
  const canvas = root.querySelector<HTMLCanvasElement>('canvas');
  expect(canvas).not.toBeNull();
  canvas!.getBoundingClientRect = () => ({
    left: 0,
    top: 0,
    width: 1280,
    height: 720,
    right: 1280,
    bottom: 720,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
  return canvas!;
};

const selectRegionButton = (root: HTMLElement) => {
  const button = root.querySelector<HTMLButtonElement>('button[aria-label="Select page region"]');
  expect(button).not.toBeNull();
  return button!;
};

const syncActiveScreencastTab = async () => {
  const ws = MockWebSocket.instances[0];
  expect(ws).toBeDefined();
  ws.onmessage?.({
    data: JSON.stringify({
      type: 'tabs_snapshot',
      tabs: [
        {
          tab_id: 'tab-1',
          title: 'Results',
          url: 'https://example.test/results',
          status: 'ready',
          active: true,
        },
      ],
    }),
  } as MessageEvent);
  await flushAsyncUpdates();
};

const dispatchCanvasMouse = (
  canvas: HTMLCanvasElement,
  type: 'mousedown' | 'mousemove' | 'mouseup',
  clientX: number,
  clientY: number,
) => {
  canvas.dispatchEvent(new MouseEvent(type, {
    bubbles: true,
    clientX,
    clientY,
    button: 0,
  }));
};

const regionAnalyzeCalls = () => post.mock.calls.filter(([url]) => (
  url === '/rpa/session/session-1/region/analyze'
));

const elementBoundsCalls = () => post.mock.calls.filter(([url]) => (
  url === '/rpa/session/session-1/region/element-bounds'
));

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

  it('projects download signals from live trace events into the recording timeline display', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'click first file name';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    mockChatSse([
      'event: trace_added\ndata: {"trace_id":"trace-download","trace_type":"ai_operation","source":"ai","description":"Click first file name","user_instruction":"Click the first row file name","signals":{"download":{"filename":"export.xlsx"}}}\n\n',
      'event: agent_done\ndata: {"message":"done","trace_count":1}\n\n',
    ]);

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    expect(root.textContent).toContain('Click first file name');
    expect(root.textContent).toContain('export.xlsx');
    expect(root.textContent).toContain('下载');

    app.unmount();
  });

  it('preserves download summaries when polling the projected session timeline', async () => {
    get.mockResolvedValue({
      data: {
        session: {
          timeline: [
            {
              kind: 'trace',
              trace_id: 'trace-download',
              trace_type: 'ai_operation',
              source: 'ai',
              action: 'ai_operation',
              title: 'Click table row column action',
              summary: 'Click table row column action，并下载 export.xlsx',
              raw_trace: {
                signals: {
                  download: {
                    filename: 'export.xlsx',
                  },
                },
              },
            },
          ],
        },
      },
    });

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();

    expect(root.textContent).toContain('Click table row column action');
    expect(root.textContent).toContain('export.xlsx');
    expect(root.textContent).toContain('下载');

    app.unmount();
  });

  it('includes pending region id in the next assistant chat request', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    mockChatSse([
      'event: agent_done\ndata: {"message":"Task completed","trace_count":1}\n\n',
    ]);

    const { app, root } = await mountRecorderPage();
    dispatchSelectedRegion(root, {
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

  it('reenables the chat input when a stream closes without a terminal event', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    mockChatSse([
      'event: agent_thought\ndata: {"text":"Planning one trace-first recording command."}\n\n',
    ]);

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'extract selected region';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    expect(textarea!.disabled).toBe(false);
    expect(textarea!.placeholder).not.toBe('Agent 运行中...');

    app.unmount();
  });

  it('keeps pending region and shows a prompt when sending empty text', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });

    const { app, root } = await mountRecorderPage();
    dispatchSelectedRegion(root, {
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

  it('keeps selected region available for retry when chat fetch fails', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    const encoder = new TextEncoder();
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({
        ok: true,
        body: {
          getReader: () => {
            let done = false;
            return {
              read: () => {
                if (done) return Promise.resolve({ done: true, value: undefined });
                done = true;
                return Promise.resolve({
                  done: false,
                  value: encoder.encode('event: agent_done\ndata: {"message":"Task completed","trace_count":1}\n\n'),
                });
              },
            };
          },
        },
      });
    vi.stubGlobal('fetch', fetchMock);

    const { app, root } = await mountRecorderPage();
    dispatchSelectedRegion(root, {
      regionId: 'region-retry',
      kind: 'page_region',
      summary: 'Retry target area',
    });
    await flushAsyncUpdates();

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'try first';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    expect(root.textContent).toContain('Retry target area');

    textarea!.value = 'try again';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    const [, retryInit] = fetchMock.mock.calls[1];
    expect(JSON.parse(String((retryInit as RequestInit).body))).toMatchObject({
      message: 'try again',
      mode: 'trace_first',
      region_id: 'region-retry',
    });

    app.unmount();
  });

  it('does not clear a later selected region when an earlier no-region chat completes', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    let firstRead: (() => Promise<{ done: boolean; value?: Uint8Array }>) | null = null;
    const encoder = new TextEncoder();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        body: {
          getReader: () => {
            let readCount = 0;
            return {
              read: () => {
                if (readCount > 0) return Promise.resolve({ done: true, value: undefined });
                readCount += 1;
                return firstRead!();
              },
            };
          },
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        body: {
          getReader: () => {
            let done = false;
            return {
              read: () => {
                if (done) return Promise.resolve({ done: true, value: undefined });
                done = true;
                return Promise.resolve({
                  done: false,
                  value: encoder.encode('event: agent_done\ndata: {"message":"Task completed","trace_count":1}\n\n'),
                });
              },
            };
          },
        },
      });
    vi.stubGlobal('fetch', fetchMock);

    const { app, root } = await mountRecorderPage();
    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'run without region';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    let resolveFirstRead: ((result: { done: boolean; value?: Uint8Array }) => void) | null = null;
    firstRead = () => new Promise((resolve) => {
      resolveFirstRead = resolve;
    });

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    dispatchSelectedRegion(root, {
      regionId: 'region-after-start',
      kind: 'page_region',
      summary: 'Selected while first chat runs',
    });
    await flushAsyncUpdates();
    expect(root.textContent).toContain('Selected while first chat runs');

    resolveFirstRead!({
      done: false,
      value: encoder.encode('event: agent_done\ndata: {"message":"Task completed","trace_count":0}\n\n'),
    });
    await flushAsyncUpdates();

    textarea!.value = 'use later region';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    const [, secondInit] = fetchMock.mock.calls[1];
    expect(JSON.parse(String((secondInit as RequestInit).body))).toMatchObject({
      message: 'use later region',
      mode: 'trace_first',
      region_id: 'region-after-start',
    });

    app.unmount();
  });

  it('does not clear a later selected region when an earlier region chat completes', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    let firstRead: (() => Promise<{ done: boolean; value?: Uint8Array }>) | null = null;
    const encoder = new TextEncoder();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        body: {
          getReader: () => {
            let readCount = 0;
            return {
              read: () => {
                if (readCount > 0) return Promise.resolve({ done: true, value: undefined });
                readCount += 1;
                return firstRead!();
              },
            };
          },
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        body: {
          getReader: () => {
            let done = false;
            return {
              read: () => {
                if (done) return Promise.resolve({ done: true, value: undefined });
                done = true;
                return Promise.resolve({
                  done: false,
                  value: encoder.encode('event: agent_done\ndata: {"message":"Task completed","trace_count":1}\n\n'),
                });
              },
            };
          },
        },
      });
    vi.stubGlobal('fetch', fetchMock);

    const { app, root } = await mountRecorderPage();
    dispatchSelectedRegion(root, {
      regionId: 'region-a',
      kind: 'page_region',
      summary: 'Initial selected area',
    });
    await flushAsyncUpdates();

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'run with region a';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    let resolveFirstRead: ((result: { done: boolean; value?: Uint8Array }) => void) | null = null;
    firstRead = () => new Promise((resolve) => {
      resolveFirstRead = resolve;
    });

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    const [, firstInit] = fetchMock.mock.calls[0];
    expect(JSON.parse(String((firstInit as RequestInit).body))).toMatchObject({
      message: 'run with region a',
      mode: 'trace_first',
      region_id: 'region-a',
    });

    dispatchSelectedRegion(root, {
      regionId: 'region-b',
      kind: 'page_region',
      summary: 'Replacement selected area',
    });
    await flushAsyncUpdates();
    expect(root.textContent).toContain('Replacement selected area');

    resolveFirstRead!({
      done: false,
      value: encoder.encode('event: agent_done\ndata: {"message":"Task completed","trace_count":1}\n\n'),
    });
    await flushAsyncUpdates();

    textarea!.value = 'run with region b';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    const [, secondInit] = fetchMock.mock.calls[1];
    expect(JSON.parse(String((secondInit as RequestInit).body))).toMatchObject({
      message: 'run with region b',
      mode: 'trace_first',
      region_id: 'region-b',
    });

    app.unmount();
  });

  it('does not forward canvas mouse events to screencast while selecting a region', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);
    const ws = MockWebSocket.instances[0];
    ws.send.mockClear();

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    expect(root.textContent).toContain('Click an element or drag to select a region · Esc to cancel');

    dispatchCanvasMouse(canvas, 'mousedown', 20, 30);
    dispatchCanvasMouse(canvas, 'mousemove', 120, 150);
    dispatchCanvasMouse(canvas, 'mouseup', 120, 150);
    await flushAsyncUpdates();

    expect(ws.send).not.toHaveBeenCalled();

    app.unmount();
  });

  it('analyzes a valid canvas drag and sends the next chat with the selected region id', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/analyze') {
        return Promise.resolve({
          data: {
            region_id: 'region-42',
            summary: 'Search results area',
            inferred_kind: 'list_region',
            evidence: { nodeCount: 5 },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
    mockChatSse([
      'event: agent_done\ndata: {"message":"Task completed","trace_count":1}\n\n',
    ]);

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 20, 30);
    dispatchCanvasMouse(canvas, 'mousemove', 120, 150);
    dispatchCanvasMouse(canvas, 'mouseup', 120, 150);
    await flushAsyncUpdates();

    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/region/analyze', {
      tab_id: 'tab-1',
      rect: {
        x: 20,
        y: 30,
        width: 100,
        height: 120,
      },
      viewport: {
        width: 1280,
        height: 720,
      },
    });
    expect(root.textContent).toContain('Search results area');

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'extract selected results';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, requestInit] = fetchMock.mock.calls[0];
    const body = JSON.parse(String((requestInit as RequestInit).body));
    expect(body).toEqual({
      message: 'extract selected results',
      mode: 'trace_first',
      region_id: 'region-42',
    });
    expect(body).not.toHaveProperty('region_context');
    expect(body).not.toHaveProperty('evidence');
    expect(body).not.toHaveProperty('rect');
    expect(body).not.toHaveProperty('viewport');

    app.unmount();
  });

  it('resolves clicked element bounds and analyzes the element through the existing region path', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/element-bounds') {
        return Promise.resolve({
          data: {
            rect: { x: 64, y: 72, width: 156, height: 36 },
            tag: 'button',
            role: 'button',
            name: 'Export',
            text: 'Export',
          },
        });
      }
      if (url === '/rpa/session/session-1/region/analyze') {
        return Promise.resolve({
          data: {
            region_id: 'region-button',
            summary: 'Region 156x36, contains 1 element',
            inferred_kind: 'button_region',
            evidence: { nodeCount: 1 },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousemove', 80, 90);
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 80, 90);
    dispatchCanvasMouse(canvas, 'mouseup', 80, 90);
    await flushAsyncUpdates();

    expect(elementBoundsCalls()).toHaveLength(1);
    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/region/element-bounds', {
      tab_id: 'tab-1',
      point: { x: 80, y: 90 },
      viewport: {
        width: 1280,
        height: 720,
      },
    });
    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/region/analyze', {
      tab_id: 'tab-1',
      rect: { x: 64, y: 72, width: 156, height: 36 },
      viewport: {
        width: 1280,
        height: 720,
      },
    });
    expect(root.textContent).toContain('Export');

    app.unmount();
  });

  it('does not complete a clicked element selection after Escape cancels a pending bounds request', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    const boundsDeferred = createDeferred<unknown>();
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/element-bounds') {
        return boundsDeferred.promise;
      }
      if (url === '/rpa/session/session-1/region/analyze') {
        return Promise.resolve({
          data: {
            region_id: 'region-canceled',
            summary: 'Canceled element',
            inferred_kind: 'button_region',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 80, 90);
    dispatchCanvasMouse(canvas, 'mouseup', 80, 90);
    await flushAsyncUpdates();

    canvas.dispatchEvent(new KeyboardEvent('keydown', {
      bubbles: true,
      key: 'Escape',
      code: 'Escape',
    }));
    await flushAsyncUpdates();

    boundsDeferred.resolve({
      data: {
        rect: { x: 64, y: 72, width: 156, height: 36 },
        tag: 'button',
        role: 'button',
        name: 'Export',
        text: 'Export',
      },
    });
    await flushAsyncUpdates();

    expect(elementBoundsCalls()).toHaveLength(1);
    expect(regionAnalyzeCalls()).toHaveLength(0);
    expect(root.textContent).not.toContain('Canceled element');
    expect(root.textContent).not.toContain('Export');

    app.unmount();
  });

  it('re-resolves bounds when clicking outside the cached hover element', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    let boundsCount = 0;
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/element-bounds') {
        boundsCount += 1;
        return Promise.resolve({
          data: boundsCount === 1
            ? {
                rect: { x: 64, y: 72, width: 156, height: 36 },
                tag: 'button',
                role: 'button',
                name: 'Export',
                text: 'Export',
              }
            : {
                rect: { x: 360, y: 72, width: 180, height: 36 },
                tag: 'input',
                role: 'textbox',
                name: 'Search',
                text: '',
              },
        });
      }
      if (url === '/rpa/session/session-1/region/analyze') {
        return Promise.resolve({
          data: {
            region_id: 'region-search',
            summary: 'Region 180x36, contains 1 element',
            inferred_kind: 'input_region',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousemove', 80, 90);
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 400, 90);
    dispatchCanvasMouse(canvas, 'mouseup', 400, 90);
    await flushAsyncUpdates();

    expect(elementBoundsCalls()).toHaveLength(2);
    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/region/analyze', {
      tab_id: 'tab-1',
      rect: { x: 360, y: 72, width: 180, height: 36 },
      viewport: {
        width: 1280,
        height: 720,
      },
    });
    expect(root.textContent).toContain('Search (input)');

    app.unmount();
  });

  it('only resolves a clicked element once when repeated mouseup arrives before bounds resolve', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    const boundsDeferred = createDeferred<unknown>();
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/element-bounds') {
        return boundsDeferred.promise;
      }
      if (url === '/rpa/session/session-1/region/analyze') {
        return Promise.resolve({
          data: {
            region_id: 'region-click-once',
            summary: 'Export button',
            inferred_kind: 'button_region',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 80, 90);
    dispatchCanvasMouse(canvas, 'mouseup', 80, 90);
    dispatchCanvasMouse(canvas, 'mouseup', 80, 90);
    await flushAsyncUpdates();

    expect(elementBoundsCalls()).toHaveLength(1);

    boundsDeferred.resolve({
      data: {
        rect: { x: 64, y: 72, width: 156, height: 36 },
        tag: 'button',
        role: 'button',
        name: 'Export',
        text: 'Export',
      },
    });
    await flushAsyncUpdates();

    expect(regionAnalyzeCalls()).toHaveLength(1);
    expect(root.textContent).toContain('Export (button)');

    app.unmount();
  });

  it('only analyzes once when mouseup is delivered repeatedly before the first analysis resolves', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    const analyzeDeferred = createDeferred<unknown>();
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/analyze') {
        return analyzeDeferred.promise;
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 20, 30);
    dispatchCanvasMouse(canvas, 'mousemove', 120, 150);
    dispatchCanvasMouse(canvas, 'mouseup', 120, 150);
    dispatchCanvasMouse(canvas, 'mouseup', 120, 150);
    await flushAsyncUpdates();

    expect(regionAnalyzeCalls()).toHaveLength(1);

    analyzeDeferred.resolve({
      data: {
        region_id: 'region-once',
        summary: 'Single analyzed area',
        inferred_kind: 'list_region',
      },
    });
    await flushAsyncUpdates();

    expect(root.textContent).toContain('Single analyzed area');

    app.unmount();
  });

  it('keeps the newer selected region when an older analysis resolves later', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    let analyzeCount = 0;
    const firstAnalyze = createDeferred<unknown>();
    const secondAnalyze = createDeferred<unknown>();
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/analyze') {
        analyzeCount += 1;
        return analyzeCount === 1 ? firstAnalyze.promise : secondAnalyze.promise;
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 20, 30);
    dispatchCanvasMouse(canvas, 'mousemove', 120, 150);
    dispatchCanvasMouse(canvas, 'mouseup', 120, 150);
    await flushAsyncUpdates();
    expect(regionAnalyzeCalls()).toHaveLength(1);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 200, 180);
    dispatchCanvasMouse(canvas, 'mousemove', 360, 320);
    dispatchCanvasMouse(canvas, 'mouseup', 360, 320);
    await flushAsyncUpdates();
    expect(regionAnalyzeCalls()).toHaveLength(2);

    secondAnalyze.resolve({
      data: {
        region_id: 'region-new',
        summary: 'Newest selected area',
        inferred_kind: 'list_region',
      },
    });
    await flushAsyncUpdates();

    expect(root.textContent).toContain('Newest selected area');
    expect(root.textContent).not.toContain('Stale selected area');

    firstAnalyze.resolve({
      data: {
        region_id: 'region-old',
        summary: 'Stale selected area',
        inferred_kind: 'list_region',
      },
    });
    await flushAsyncUpdates();

    expect(root.textContent).toContain('Newest selected area');
    expect(root.textContent).not.toContain('Stale selected area');

    app.unmount();
  });

  it('finalizes a valid region when mouseup happens outside the canvas', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/analyze') {
        return Promise.resolve({
          data: {
            region_id: 'region-outside',
            summary: 'Released outside area',
            inferred_kind: 'list_region',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    dispatchCanvasMouse(canvas, 'mousedown', 20, 30);
    dispatchCanvasMouse(canvas, 'mousemove', 120, 150);
    document.dispatchEvent(new MouseEvent('mouseup', {
      bubbles: true,
      clientX: 1400,
      clientY: 900,
      button: 0,
    }));
    await flushAsyncUpdates();

    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/region/analyze', {
      tab_id: 'tab-1',
      rect: {
        x: 20,
        y: 30,
        width: 100,
        height: 120,
      },
      viewport: {
        width: 1280,
        height: 720,
      },
    });
    expect(root.textContent).toContain('Released outside area');
    expect(root.textContent).not.toContain('Click an element or drag to select a region · Esc to cancel');

    app.unmount();
  });

  it('cancels region selection with Escape without analyzing', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    expect(root.textContent).toContain('Click an element or drag to select a region · Esc to cancel');

    canvas.dispatchEvent(new KeyboardEvent('keydown', {
      bubbles: true,
      key: 'Escape',
      code: 'Escape',
    }));
    await flushAsyncUpdates();

    expect(root.textContent).not.toContain('Click an element or drag to select a region · Esc to cancel');
    expect(post).not.toHaveBeenCalledWith(
      '/rpa/session/session-1/region/analyze',
      expect.anything(),
    );

    app.unmount();
  });

  it('cancels tiny click-like selections when no element bounds can be resolved', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });
    post.mockImplementation((url: string) => {
      if (url === '/rpa/session/start') {
        return Promise.resolve({
          data: {
            status: 'success',
            session: { id: 'session-1' },
          },
        });
      }
      if (url === '/rpa/session/session-1/region/element-bounds') {
        return Promise.resolve({
          data: {
            rect: null,
            warnings: ['No element at point'],
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    expect(root.textContent).toContain('Click an element or drag to select a region · Esc to cancel');

    dispatchCanvasMouse(canvas, 'mousedown', 20, 30);
    dispatchCanvasMouse(canvas, 'mousemove', 24, 35);
    dispatchCanvasMouse(canvas, 'mouseup', 24, 35);
    await flushAsyncUpdates();

    expect(elementBoundsCalls()).toHaveLength(1);
    expect(root.textContent).not.toContain('Click an element or drag to select a region · Esc to cancel');
    expect(post).not.toHaveBeenCalledWith(
      '/rpa/session/session-1/region/analyze',
      expect.anything(),
    );

    app.unmount();
  });

  it('hides harness capture controls when backend config disables capture', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/rpa/harness/config') {
        return Promise.resolve({ data: { status: 'success', capture_enabled: false } });
      }
      return Promise.resolve({ data: { session: { traces: [] } } });
    });

    const { app, root } = await mountRecorderPage();
    await flushAsyncUpdates();

    expect(root.querySelector('[data-testid="harness-capture-panel"]')).toBeNull();
    expect(post.mock.calls.some(([url]) => String(url).includes('/harness-capture/start'))).toBe(false);

    app.unmount();
  });

  it('starts full sop harness capture only after an explicit click', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/rpa/harness/config') {
        return Promise.resolve({ data: { status: 'success', capture_enabled: true } });
      }
      return Promise.resolve({ data: { session: { traces: [] } } });
    });

    const { app, root } = await mountRecorderPage();
    await flushAsyncUpdates();

    expect(root.querySelector('[data-testid="harness-capture-panel"]')).not.toBeNull();
    expect(post.mock.calls.some(([url]) => String(url).includes('/harness-capture/start'))).toBe(false);

    root.querySelector<HTMLButtonElement>('[data-testid="harness-start-full-sop"]')?.click();
    await flushAsyncUpdates();

    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/harness-capture/start', {
      capture_scope: 'full_sop',
    });

    app.unmount();
  });

  it('marks the next natural-language step without preselecting a trace index', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/rpa/harness/config') {
        return Promise.resolve({ data: { status: 'success', capture_enabled: true } });
      }
      return Promise.resolve({
        data: {
          session: {
            traces: [
              { trace_id: 'trace-one', trace_type: 'manual_action', action: 'click' },
              { trace_id: 'trace-two', trace_type: 'manual_action', action: 'fill' },
            ],
          },
        },
      });
    });

    const { app, root } = await mountRecorderPage();
    await vi.advanceTimersByTimeAsync(3000);
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('[data-testid="harness-mark-next-step"]')?.click();
    await flushAsyncUpdates();
    await flushAsyncUpdates();

    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/harness-capture/start', {
      capture_scope: 'selected_steps',
    });
    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/harness-capture/next-natural-language-step/select');
    expect(post.mock.calls.some(([url]) => String(url).includes('/harness-capture/steps/'))).toBe(false);

    app.unmount();
  });

  it('clears the pending next natural-language capture when the streamed step returns capture state', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/rpa/harness/config') {
        return Promise.resolve({ data: { status: 'success', capture_enabled: true } });
      }
      return Promise.resolve({ data: { session: { traces: [] } } });
    });

    const { app, root } = await mountRecorderPage();
    await flushAsyncUpdates();

    root.querySelector<HTMLButtonElement>('[data-testid="harness-mark-next-step"]')?.click();
    await flushAsyncUpdates();
    await flushAsyncUpdates();

    const nextStepButton = root.querySelector<HTMLButtonElement>('[data-testid="harness-mark-next-step"]');
    expect(nextStepButton?.classList.contains('bg-emerald-50')).toBe(true);
    expect(root.textContent).toContain('Next NL Step pending');
    expect(root.querySelector<HTMLButtonElement>('[data-testid="harness-start-full-sop"]')?.disabled).toBe(true);

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea');
    expect(textarea).not.toBeNull();
    textarea!.value = 'Extract star count';
    textarea!.dispatchEvent(new Event('input'));
    await flushAsyncUpdates();
    mockChatSse([
      'event: agent_step_done\ndata: {"success":true,"output":{"star_count":"1k"},"capture":{"capture_scope":"selected_steps","selected_step_indexes":[],"pending_natural_language_step_captures":0}}\n\n',
      'event: agent_done\ndata: {"message":"done","trace_count":1,"capture":{"capture_scope":"selected_steps","selected_step_indexes":[],"pending_natural_language_step_captures":0}}\n\n',
    ]);

    root.querySelector<HTMLButtonElement>('button.flex.h-8.w-8')?.click();
    await flushAsyncUpdates();

    expect(root.textContent).not.toContain('Next NL Step pending');
    expect(root.textContent).toContain('Selected Step active');
    expect(nextStepButton?.classList.contains('bg-emerald-50')).toBe(false);
    expect(root.querySelector<HTMLButtonElement>('[data-testid="harness-start-full-sop"]')?.disabled).toBe(false);

    app.unmount();
  });
});
