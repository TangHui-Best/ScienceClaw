// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { createI18n } from 'vue-i18n';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../locales/en';
import zh from '../../locales/zh';

const {
  routeState,
  push,
  getRpaMcpTool,
  getRpaMcpExecutionPlan,
  previewRpaMcpTool,
  testPreviewRpaMcpTool,
  apiGet,
  apiPost,
  showErrorToast,
  showSuccessToast,
} = vi.hoisted(() => ({
  routeState: {
    params: { toolId: 'tool-1' } as Record<string, string>,
    query: { mode: 'view' } as Record<string, string>,
  },
  push: vi.fn(),
  getRpaMcpTool: vi.fn(),
  getRpaMcpExecutionPlan: vi.fn(),
  previewRpaMcpTool: vi.fn(),
  testPreviewRpaMcpTool: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  showErrorToast: vi.fn(),
  showSuccessToast: vi.fn(),
}));

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push }),
}));

vi.mock('@/api/rpaMcp', () => ({
  createRpaMcpTool: vi.fn(),
  getRpaMcpTool: (...args: unknown[]) => getRpaMcpTool(...args),
  getRpaMcpExecutionPlan: (...args: unknown[]) => getRpaMcpExecutionPlan(...args),
  previewRpaMcpTool: (...args: unknown[]) => previewRpaMcpTool(...args),
  testPreviewRpaMcpTool: (...args: unknown[]) => testPreviewRpaMcpTool(...args),
  testRpaMcpTool: vi.fn(),
  updateRpaMcpTool: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}));

vi.mock('@/utils/toast', () => ({
  showErrorToast: (...args: unknown[]) => showErrorToast(...args),
  showSuccessToast: (...args: unknown[]) => showSuccessToast(...args),
}));

async function flushAsyncUpdates() {
  await Promise.resolve();
  await Promise.resolve();
  await nextTick();
}

async function mountViewPage(locale = 'en') {
  const { default: McpToolEditorPage } = await import('./McpToolEditorPage.vue');
  const root = document.createElement('div');
  document.body.appendChild(root);

  const app = createApp(McpToolEditorPage);
  app.use(createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages: { en, zh },
  }));
  app.mount(root);
  await flushAsyncUpdates();

  return { app, root };
}

const makePreview = (overrides: Record<string, unknown> = {}) => ({
  id: 'preview-1',
  enabled: true,
  name: 'Invoice Export',
  tool_name: 'invoice_export',
  description: 'Export invoices from the dashboard',
  requires_cookies: false,
  allowed_domains: ['example.com'],
  post_auth_start_url: 'https://example.com/dashboard',
  steps: [],
  params: {},
  input_schema: { type: 'object', properties: {} },
  output_schema: { type: 'object', properties: {} },
  recommended_output_schema: { type: 'object', properties: {} },
  sanitize_report: {
    removed_steps: [],
    removed_params: [],
    warnings: [],
  },
  source: {},
  ...overrides,
});

async function mountCreatePage(locale = 'en', timeline: Array<Record<string, unknown>> = []) {
  routeState.params = {};
  routeState.query = { sessionId: 'session-1' };
  apiGet.mockResolvedValue({
    data: {
      session: {
        id: 'session-1',
        timeline,
      },
    },
  });
  const { default: McpToolEditorPage } = await import('./McpToolEditorPage.vue');
  const root = document.createElement('div');
  document.body.appendChild(root);

  const app = createApp(McpToolEditorPage);
  app.use(createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages: { en, zh },
  }));
  app.mount(root);
  await flushAsyncUpdates();

  return { app, root };
}

describe('McpToolEditorPage view mode', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
    vi.resetModules();
    routeState.params = { toolId: 'tool-1' };
    routeState.query = { mode: 'view' };
  });

  it('loads the execution script only after switching to the files tab', async () => {
    getRpaMcpTool.mockResolvedValue({
      id: 'tool-1',
      enabled: true,
      name: 'Invoice Export',
      tool_name: 'invoice_export',
      description: 'Export invoices from the dashboard',
      requires_cookies: true,
      allowed_domains: ['example.com'],
      post_auth_start_url: 'https://example.com/dashboard',
      steps: [
        {
          id: 'step_1',
          action: 'click',
          description: 'Click export button',
          validation: { status: 'ok', details: '' },
          locator_candidates: [],
        },
      ],
      params: {
        query: {
          type: 'string',
          description: 'Invoice query',
          required: true,
          source_param: 'query',
        },
      },
      input_schema: {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Invoice query',
          },
        },
        required: ['query'],
      },
      output_schema: { type: 'object', properties: {} },
      recommended_output_schema: { type: 'object', properties: {} },
      sanitize_report: {
        removed_steps: [],
        removed_params: [],
        warnings: [],
      },
      source: {},
    });
    getRpaMcpExecutionPlan.mockResolvedValue({
      tool_id: 'tool-1',
      generated_at: '2026-04-24T12:00:00+08:00',
      requires_cookies: true,
      compiled_steps: [],
      compiled_script: "async def run(page):\n    await page.click('text=Export invoice')\n",
      input_schema: { type: 'object', properties: {} },
      output_schema: { type: 'object', properties: {} },
      source_hash: 'hash-1',
    });

    const { app, root } = await mountViewPage('en');

    const initialText = root.textContent || '';
    expect(initialText).toContain('Overview');
    expect(initialText).toContain('Basic Info');
    const readonlyInputs = Array.from(root.querySelectorAll('input')) as HTMLInputElement[];
    expect(readonlyInputs.some((input) => input.value === 'Invoice Export')).toBe(true);
    expect(getRpaMcpExecutionPlan).not.toHaveBeenCalled();

    const filesButton = Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes('Files'));
    expect(filesButton).toBeTruthy();
    filesButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushAsyncUpdates();

    expect(getRpaMcpExecutionPlan).toHaveBeenCalledWith('tool-1');
    expect(root.textContent || '').toContain("await page.click('text=Export invoice')");

    app.unmount();
  });
});

describe('McpToolEditorPage trace locator promotion', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
    vi.resetModules();
    routeState.params = { toolId: 'tool-1' };
    routeState.query = { mode: 'view' };
  });

  it('disables locator promotion when a recorded step has no trace id', async () => {
    previewRpaMcpTool.mockResolvedValue(makePreview({
      steps: [
        {
          id: 'step_1',
          action: 'click',
          description: 'Click export button',
          configurable: true,
          locator_candidates: [
            { kind: 'role', selected: false, locator: { method: 'role', role: 'button', name: 'Export' } },
          ],
        },
      ],
    }));

    const { app, root } = await mountCreatePage('en', [
      {
        kind: 'trace',
        action: 'click',
        title: 'Click export button',
        summary: 'Click export button',
        editable: true,
        locator_candidates: [
          { kind: 'role', selected: false, locator: { method: 'role', role: 'button', name: 'Export' } },
        ],
      },
    ]);

    root.querySelector('article button')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushAsyncUpdates();
    const useLocatorButton = Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes('Use this locator')) as HTMLButtonElement | undefined;
    expect(useLocatorButton).toBeTruthy();
    expect(useLocatorButton?.disabled).toBe(true);
    useLocatorButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushAsyncUpdates();

    expect(apiPost).not.toHaveBeenCalled();
    app.unmount();
  });

  it('promotes locator candidates through the trace endpoint only', async () => {
    previewRpaMcpTool.mockResolvedValue(makePreview({
      steps: [
        {
          id: 'step_1',
          traceId: 'trace-1',
          action: 'click',
          description: 'Click export button',
          configurable: true,
          locator_candidates: [
            { kind: 'role', selected: false, locator: { method: 'role', role: 'button', name: 'Export' } },
          ],
        },
      ],
    }));
    apiPost.mockResolvedValue({ data: {} });

    const { app, root } = await mountCreatePage('en', [
      {
        kind: 'trace',
        trace_id: 'trace-1',
        action: 'click',
        title: 'Click export button',
        summary: 'Click export button',
        editable: true,
        locator_candidates: [
          { kind: 'role', selected: false, locator: { method: 'role', role: 'button', name: 'Export' } },
        ],
      },
    ]);

    root.querySelector('article button')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushAsyncUpdates();
    const useLocatorButton = Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes('Use this locator')) as HTMLButtonElement | undefined;
    expect(useLocatorButton).toBeTruthy();
    useLocatorButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushAsyncUpdates();

    expect(apiPost).toHaveBeenCalledWith('/rpa/session/session-1/trace/trace-1/locator', { candidate_index: 0 });
    expect(apiPost).not.toHaveBeenCalledWith('/rpa/session/session-1/step/0/locator', expect.anything());
    app.unmount();
  });

  it('does not confirm source_step_index for params without source_trace_id', async () => {
    previewRpaMcpTool.mockResolvedValue(makePreview({
      params: {
        query: {
          type: 'string',
          description: 'Invoice query',
          required: false,
          source_param: 'query',
          source_step_index: 2,
        },
      },
      input_schema: {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Invoice query',
          },
        },
      },
    }));
    testPreviewRpaMcpTool.mockResolvedValue({ success: true, message: 'ok' });

    const { app, root } = await mountCreatePage('en');

    const runPreviewButton = root.querySelector('[data-preview-test-action]') as HTMLButtonElement | null;
    expect(runPreviewButton).toBeTruthy();
    runPreviewButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushAsyncUpdates();

    const payload = testPreviewRpaMcpTool.mock.calls[0][1];
    expect(payload.params.query).not.toHaveProperty('source_step_index');
    expect(payload.params.query).not.toHaveProperty('source_trace_id');
    app.unmount();
  });
});
