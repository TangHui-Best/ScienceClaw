// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
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
    expect(root.textContent).toContain('Drag to select page region · Esc to cancel');

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
    expect(JSON.parse(String((requestInit as RequestInit).body))).toMatchObject({
      message: 'extract selected results',
      mode: 'trace_first',
      region_id: 'region-42',
    });

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
    expect(root.textContent).not.toContain('Drag to select page region · Esc to cancel');

    app.unmount();
  });

  it('cancels region selection with Escape without analyzing', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    expect(root.textContent).toContain('Drag to select page region · Esc to cancel');

    canvas.dispatchEvent(new KeyboardEvent('keydown', {
      bubbles: true,
      key: 'Escape',
      code: 'Escape',
    }));
    await flushAsyncUpdates();

    expect(root.textContent).not.toContain('Drag to select page region · Esc to cancel');
    expect(post).not.toHaveBeenCalledWith(
      '/rpa/session/session-1/region/analyze',
      expect.anything(),
    );

    app.unmount();
  });

  it('silently cancels tiny region selections without analyzing', async () => {
    get.mockResolvedValue({ data: { session: { timeline: [] } } });

    const { app, root } = await mountRecorderPage();
    await syncActiveScreencastTab();
    const canvas = getCanvas(root);

    selectRegionButton(root).click();
    await flushAsyncUpdates();
    expect(root.textContent).toContain('Drag to select page region · Esc to cancel');

    dispatchCanvasMouse(canvas, 'mousedown', 20, 30);
    dispatchCanvasMouse(canvas, 'mousemove', 24, 35);
    dispatchCanvasMouse(canvas, 'mouseup', 24, 35);
    await flushAsyncUpdates();

    expect(root.textContent).not.toContain('Drag to select page region · Esc to cancel');
    expect(post).not.toHaveBeenCalledWith(
      '/rpa/session/session-1/region/analyze',
      expect.anything(),
    );

    app.unmount();
  });
});
