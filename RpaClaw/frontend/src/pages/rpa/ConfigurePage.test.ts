// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';

const push = vi.fn();
const get = vi.fn();
const post = vi.fn();
const deleteRequest = vi.fn();

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { sessionId: 'session-1' } }),
  useRouter: () => ({ push }),
}));

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    delete: (...args: unknown[]) => deleteRequest(...args),
  },
}));

vi.mock('@/components/rpa/RpaFlowGuide.vue', () => ({
  default: {
    name: 'RpaFlowGuideStub',
    props: ['secondaryActions'],
    emits: ['secondary-action'],
    template: `
      <div data-testid="flow-guide">
        <button
          v-for="action in secondaryActions"
          :key="action.id"
          type="button"
          :disabled="action.disabled"
          @click="$emit('secondary-action', action.id)"
        >
          {{ action.label }}
        </button>
      </div>
    `,
  },
}));

vi.mock('@/components/rpa/RpaDiscardRecordingDialog.vue', () => ({
  default: {
    name: 'RpaDiscardRecordingDialogStub',
    template: '<div />',
  },
}));

vi.mock('@/components/rpa/RpaStepTimeline.vue', () => ({
  default: {
    name: 'RpaStepTimelineStub',
    props: ['steps'],
    emits: ['promote-locator'],
    template: `
      <div data-testid="step-timeline">
        <span>{{ steps.length }} steps</span>
        <div
          v-for="(step, index) in steps"
          :key="step.id"
          data-testid="timeline-step"
        >
          {{ step.description }} {{ step.label }}
          <button
            v-if="step.locator_candidates?.length"
            type="button"
            data-testid="promote-locator"
            @click="$emit('promote-locator', { step, stepIndex: index, candidateIndex: 0 })"
          >
            Promote
          </button>
        </div>
      </div>
    `,
  },
}));

vi.mock('@/components/ui/dialog', () => ({
  Dialog: {
    name: 'DialogStub',
    props: ['open'],
    template: '<div v-if="open" data-testid="script-dialog"><slot /></div>',
  },
  DialogContent: {
    name: 'DialogContentStub',
    template: '<div><slot /></div>',
  },
  DialogHeader: {
    name: 'DialogHeaderStub',
    template: '<div><slot /></div>',
  },
  DialogTitle: {
    name: 'DialogTitleStub',
    template: '<div><slot /></div>',
  },
}));

const flushAsyncUpdates = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await nextTick();
};

const mountConfigurePage = async () => {
  const { default: ConfigurePage } = await import('./ConfigurePage.vue');
  const root = document.createElement('div');
  document.body.appendChild(root);

  const app = createApp(ConfigurePage);
  app.mount(root);
  await flushAsyncUpdates();

  return { app, root };
};

const mockCommonRequests = (session: any) => {
  get.mockImplementation((url: string) => {
    if (url === '/credentials') return Promise.resolve({ data: { credentials: [] } });
    if (url === '/rpa/session/session-1/skill-config-draft') {
      return Promise.resolve({ data: { draft: null } });
    }
    if (url === '/rpa/session/session-1') {
      return Promise.resolve({ data: { session } });
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
  post.mockResolvedValue({ data: { script: 'print("generated script")' } });
  deleteRequest.mockResolvedValue({ data: {} });
};

describe('ConfigurePage script preview entry', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
    vi.resetModules();
  });

  it('keeps the top preview action without rendering an inline script preview panel', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/credentials') return Promise.resolve({ data: { credentials: [] } });
      return Promise.resolve({
        data: {
          session: {
            url: 'https://github.com/trending',
            steps: [
              { id: 'step-1', action: 'goto', url: 'https://github.com/trending' },
            ],
          },
        },
      });
    });
    post.mockResolvedValue({ data: { script: 'print("generated script")' } });

    const { app, root } = await mountConfigurePage();

    expect(root.textContent).toContain('预览脚本');
    expect(root.textContent).not.toContain('脚本预览');
    expect(root.textContent).not.toContain('generated script');

    app.unmount();
  });

  it('renders and derives config from timeline projection when session has no legacy steps', async () => {
    mockCommonRequests({
      timeline: [
        {
          kind: 'trace',
          trace_id: 'trace-open',
          action: 'navigate',
          title: 'Open search page',
          summary: 'https://example.test/search',
          url: 'https://example.test/search',
        },
        {
          kind: 'trace',
          trace_id: 'trace-fill-query',
          action: 'fill',
          title: 'Fill query',
          summary: 'Search terms',
          locator: { method: 'role', role: 'textbox', name: 'Search terms' },
          url: 'https://example.test/search',
          raw_trace: { value: 'neural claws' },
        },
      ],
    });

    const { app, root } = await mountConfigurePage();

    expect(root.textContent).toContain('2 steps');
    expect(root.textContent).toContain('Open search page');
    expect(root.textContent).toContain('Fill query');
    expect(root.textContent).not.toContain('DO_NOT_USE_LEGACY');
    const inputValues = Array.from(root.querySelectorAll('input')).map((input) => input.value);
    expect(inputValues.some((value) => value.includes('example.test'))).toBe(true);
    expect(inputValues).toContain('search');

    app.unmount();
  });

  it('promotes trace-backed locators by trace id and never calls step locator endpoints', async () => {
    mockCommonRequests({
      timeline: [
        {
          kind: 'trace',
          trace_id: 'trace-fill-query',
          action: 'fill',
          title: 'Fill query',
          summary: 'Search terms',
          locator: { method: 'role', role: 'textbox', name: 'Search terms' },
          locator_candidates: [
            { kind: 'role', locator: { method: 'role', role: 'textbox', name: 'Search terms' } },
          ],
        },
      ],
    });

    const { app, root } = await mountConfigurePage();
    post.mockClear();

    const button = root.querySelector<HTMLButtonElement>('[data-testid="promote-locator"]');
    expect(button).not.toBeNull();
    button?.click();
    await flushAsyncUpdates();

    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/trace/trace-fill-query/locator', {
      candidate_index: 0,
    });
    expect(post.mock.calls.some(([url]) => String(url).includes('/step/'))).toBe(false);

    app.unmount();
  });

  it('deletes diagnostics by diagnostic id and never falls back to step deletion', async () => {
    mockCommonRequests({
      timeline: [
        {
          kind: 'diagnostic',
          diagnostic_id: 'diagnostic-fill-query',
          trace_id: 'trace-fill-query',
          action: 'fill',
          title: 'Fill query needs repair',
          summary: 'canonical_target_missing',
          validation: { status: 'broken', details: 'canonical target missing' },
        },
      ],
    });

    const { app, root } = await mountConfigurePage();

    const button = root.querySelector<HTMLButtonElement>('article button');
    expect(button).not.toBeNull();
    button?.click();
    await flushAsyncUpdates();

    expect(deleteRequest).toHaveBeenCalledWith('/rpa/session/session-1/diagnostic/diagnostic-fill-query');
    expect(deleteRequest.mock.calls.some(([url]) => String(url).includes('/step/'))).toBe(false);

    app.unmount();
  });

  it('promotes diagnostic locator candidates by related trace id', async () => {
    mockCommonRequests({
      timeline: [
        {
          kind: 'diagnostic',
          diagnostic_id: 'diagnostic-fill-query',
          trace_id: 'trace-fill-query',
          action: 'fill',
          title: 'Fill query needs repair',
          summary: 'canonical_target_missing',
          locator_candidates: [
            { kind: 'css', locator: { method: 'css', value: '#query' } },
          ],
          validation: { status: 'broken', details: 'canonical target missing' },
        },
      ],
    });

    const { app, root } = await mountConfigurePage();
    post.mockClear();

    const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>('article button'));
    const promoteButton = buttons.find((button) => button.textContent?.includes('使用此定位器'));
    expect(promoteButton).not.toBeUndefined();
    promoteButton?.click();
    await flushAsyncUpdates();

    expect(post).toHaveBeenCalledWith('/rpa/session/session-1/trace/trace-fill-query/locator', {
      candidate_index: 0,
    });
    expect(post.mock.calls.some(([url]) => String(url).includes('/step/'))).toBe(false);

    app.unmount();
  });

  it('ignores legacy poison data for display and mutation endpoints', async () => {
    mockCommonRequests({
      timeline: [
        {
          kind: 'trace',
          trace_id: 'trace-valid',
          action: 'click',
          title: 'Click valid target',
          summary: 'Valid target',
          locator_candidates: [
            { kind: 'css', locator: { method: 'css', value: '#valid' } },
          ],
        },
      ],
      steps: [
        {
          id: 'legacy-step',
          action: 'click',
          description: 'DO_NOT_USE_LEGACY step',
          locator_candidates: [{ locator: '#legacy' }],
        },
      ],
      recorded_actions: [
        { step_id: 'legacy-action', description: 'DO_NOT_USE_LEGACY action' },
      ],
      recording_diagnostics: [
        { related_step_id: 'legacy-step', failure_reason: 'DO_NOT_USE_LEGACY diagnostic' },
      ],
    });

    const { app, root } = await mountConfigurePage();
    post.mockClear();

    expect(root.textContent).toContain('Click valid target');
    expect(root.textContent).not.toContain('DO_NOT_USE_LEGACY');

    root.querySelector<HTMLButtonElement>('[data-testid="promote-locator"]')?.click();
    await flushAsyncUpdates();

    expect(post.mock.calls.some(([url]) => String(url).includes('/step/'))).toBe(false);

    app.unmount();
  });

  it('does not promote locator candidates when a projected item lacks a trace id', async () => {
    mockCommonRequests({
      timeline: [
        {
          id: 'projection-without-trace-id',
          kind: 'trace',
          action: 'click',
          title: 'Click projected target',
          summary: 'Projected target',
          locator_candidates: [
            { kind: 'css', locator: { method: 'css', value: '#projected' } },
          ],
        },
      ],
      steps: [
        {
          id: 'legacy-step',
          action: 'click',
          description: 'DO_NOT_USE_LEGACY step',
          locator_candidates: [{ locator: '#legacy' }],
        },
      ],
    });

    const { app, root } = await mountConfigurePage();
    post.mockClear();

    root.querySelector<HTMLButtonElement>('[data-testid="promote-locator"]')?.click();
    await flushAsyncUpdates();

    expect(post).not.toHaveBeenCalled();
    expect(post.mock.calls.some(([url]) => String(url).includes('/step/'))).toBe(false);

    app.unmount();
  });
});
