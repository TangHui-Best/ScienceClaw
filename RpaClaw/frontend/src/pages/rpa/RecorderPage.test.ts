// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const push = vi.fn();
const start = vi.fn();
const projection = vi.fn();
const instruction = vi.fn();
const stop = vi.fn();
const discard = vi.fn();
const manualInput = vi.fn();
const createHostSession = vi.fn();
const listModels = vi.fn();
const routeQuery: Record<string, string> = { browserSessionRef: 'browser-host-1' };

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: routeQuery }),
  useRouter: () => ({ push }),
}));
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (value: string) => value }) }));
vi.mock('@/api/rpaAgent', () => ({
  startRpaAgentSession: (...args: unknown[]) => start(...args),
  getRpaAgentProjection: (...args: unknown[]) => projection(...args),
  runRpaAgentInstruction: (...args: unknown[]) => instruction(...args),
  stopRpaAgentSession: (...args: unknown[]) => stop(...args),
  discardRpaAgentSession: (...args: unknown[]) => discard(...args),
  dispatchRpaAgentManualInput: (...args: unknown[]) => manualInput(...args),
}));
vi.mock('@/components/SandboxPreview.vue', () => ({
  default: {
    props: ['sessionId', 'manualInputDispatcher', 'manualInputDisabled'],
    template: '<button data-testid="browser-preview" :disabled="manualInputDisabled" @click="manualInputDispatcher({ input_id: \'input_canvas_1\', kind: \'click\', x: 12, y: 34 })">{{ sessionId }}</button>',
  },
}));
vi.mock('@/components/rpa/RpaStepTimeline.vue', () => ({
  default: { props: ['steps', 'isRecording'], template: '<div data-testid="timeline"><span v-if="isRecording">自动跟随</span><span v-for="step in steps" :key="step.id">{{ step.status }} {{ step.title }}</span></div>' },
}));
vi.mock('@/api/agent', () => ({ createSession: (...args: unknown[]) => createHostSession(...args) }));
vi.mock('@/api/models', () => ({ listModels: (...args: unknown[]) => listModels(...args) }));

const flush = async () => { await Promise.resolve(); await Promise.resolve(); await nextTick(); };

describe('RecorderPage greenfield creation journey', () => {
  beforeEach(() => {
    sessionStorage.clear(); document.body.innerHTML = '';
    routeQuery.browserSessionRef = 'browser-host-1';
    push.mockReset(); start.mockReset(); projection.mockReset(); instruction.mockReset(); stop.mockReset(); discard.mockReset();
    discard.mockResolvedValue({ state: 'discarded' });
    manualInput.mockReset(); manualInput.mockResolvedValue({ input_id: 'input_canvas_1', candidate_id: 'candidate-1', candidate_ids: ['candidate-1'] });
    createHostSession.mockReset(); createHostSession.mockResolvedValue({ session_id: 'created-browser-host', mode: 'browser' });
    listModels.mockReset(); listModels.mockResolvedValue([{ id: 'model-qwen', name: 'Qwen 3.7 Plus', provider: 'openai', model_name: 'qwen3.7-plus-2026-05-26', is_system: false, is_active: true }]);
    start.mockResolvedValue({ session_id: 'rca_abcdefghijklmnopqrstuvwx', state: 'recording', main_scope: { page_runtime_ref: 'page-1', frame_runtime_ref: 'frame-1' } });
    projection.mockResolvedValue({ state: 'recording', steps: [
      { row_id: 'c1:action', candidate_id: 'c1', ordinal: 1, status: 'pending', is_action: true, title: '等待结算', action_kind: 'click' },
      { row_id: 'c2:action', candidate_id: 'c2', ordinal: 2, status: 'accepted', is_action: true, title: '点击查询', action_kind: 'click', trace_id: 't2' },
      { row_id: 't2:effect:0', candidate_id: 'c2', ordinal: 2, status: 'effect', is_action: false, title: '页面导航', effect_kind: 'navigation', parent_trace_id: 't2' },
      { row_id: 'c3:action', candidate_id: 'c3', ordinal: 3, status: 'rejected', is_action: true, title: '录制失败', diagnostic_message: '目标不明确' },
    ] });
    instruction.mockResolvedValue({ actual_action_count: 2, replayable_action_count: 1, agent_result: '已提取目标订单。' });
    stop.mockResolvedValue({ state: 'stopped', creation_steps: [{ row_id: 'final:action', candidate_id: 'final', ordinal: 1, status: 'accepted', is_action: true, title: '最终步骤', action_kind: 'click', trace_id: 'trace-final' }], configuration_draft: { schema_version: 'skill-configuration-draft/v0.1', skill: { name: '未命名 SKILL', description: '请填写' }, inputs: [], secrets: [], asset_inputs: [], outputs: [], asset_outputs: [], binding_promotions: [] }, configuration_options: { binding_locations: [], readiness: { ready: true, issues: [] } } });
  });

  it('routes canvas input through the server-authored atomic manual producer', async () => {
    const { default: Page } = await import('./RecorderPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();
    root.querySelector<HTMLButtonElement>('[data-testid="browser-preview"]')!.click();
    await flush();
    expect(manualInput).toHaveBeenCalledWith('rca_abcdefghijklmnopqrstuvwx', {
      input_id: 'input_canvas_1', kind: 'click', x: 12, y: 34,
    });
    expect(projection.mock.invocationCallOrder.at(-1)).toBeGreaterThan(manualInput.mock.invocationCallOrder[0]);
    app.unmount();
  });
  afterEach(() => document.body.innerHTML = '');

  it('keeps the ScienceClaw recorder shell while running the new API journey', async () => {
    const { default: Page } = await import('./RecorderPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Page); app.mount(root); await flush();

    expect(start).toHaveBeenCalledWith('browser-host-1');
    expect(root.querySelector('[data-testid="recorder-left"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="recorder-center"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="recorder-right"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="rpa-flow-guide"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="recorder-browser-workspace"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="assistant-conversation"]')).not.toBeNull();
    expect(root.textContent).toContain('AI 录制助手');
    expect(root.textContent).toContain('自动跟随');
    expect(root.textContent).not.toContain('Candidate、CoreTrace');
    expect(root.querySelector<HTMLSelectElement>('[data-testid="assistant-model"]')?.value).toBe('model-qwen');
    await vi.waitFor(() => expect(root.textContent).toContain('pending'));
    expect(root.textContent).toContain('accepted');
    expect(root.textContent).toContain('effect'); expect(root.textContent).toContain('rejected');
    expect(root.querySelector('input[name="skill-name"]')).toBeNull();

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea[name="agent-instruction"]')!;
    textarea.value = '提取目标订单'; textarea.dispatchEvent(new Event('input')); await nextTick();
    root.querySelector<HTMLButtonElement>('[data-testid="run-agent"]')!.click(); await flush();
    expect(instruction).toHaveBeenCalledWith('rca_abcdefghijklmnopqrstuvwx', '提取目标订单', expect.any(Object), 'model-qwen');
    expect(root.textContent).toContain('提取目标订单');
    await vi.waitFor(() => expect(root.textContent).toContain('已提取目标订单。'));
    expect(root.textContent).toContain('已记录 1 个可回放步骤');
    expect(root.textContent).not.toContain('已记录 2 个可回放步骤');

    root.querySelector<HTMLButtonElement>('[data-testid="stop-recording"]')!.click();
    expect(push).not.toHaveBeenCalled();
    await flush();
    expect(stop).toHaveBeenCalledWith('rca_abcdefghijklmnopqrstuvwx');
    expect(push).toHaveBeenCalledWith({ path: '/rpa/configure', query: { sessionId: 'rca_abcdefghijklmnopqrstuvwx' } });
    app.unmount();
  });

  it('creates a generic browser host session when opened directly without query injection', async () => {
    delete routeQuery.browserSessionRef;
    vi.resetModules();
    const { default: Page } = await import('./RecorderPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Page); app.mount(root); await flush();
    expect(createHostSession).toHaveBeenCalledWith({ mode: 'browser' });
    expect(start).toHaveBeenCalledWith('created-browser-host');
    app.unmount();
  });

  it('discards the active recording session when the recorder is exited', async () => {
    const { default: Page } = await import('./RecorderPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Page); app.mount(root); await flush();

    app.unmount();
    await flush();

    expect(discard).toHaveBeenCalledTimes(1);
    expect(discard).toHaveBeenCalledWith('rca_abcdefghijklmnopqrstuvwx');
  });

  it('does not install a poller after unmount while the initial projection is in flight', async () => {
    vi.useFakeTimers();
    try {
      let resolveProjection!: (value: { state: string; steps: [] }) => void;
      projection.mockReturnValueOnce(new Promise((resolve) => { resolveProjection = resolve; }));
      const { default: Page } = await import('./RecorderPage.vue');
      const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();
      expect(projection).toHaveBeenCalledTimes(1);
      app.unmount(); resolveProjection({ state: 'recording', steps: [] }); await flush();
      await vi.advanceTimersByTimeAsync(2400); await flush();
      expect(projection).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });

  it('keeps the visible recorded steps when polling settles during stop', async () => {
    vi.useFakeTimers();
    try {
      let resolveStop!: (value: Record<string, unknown>) => void;
      stop.mockReturnValueOnce(new Promise((resolve) => { resolveStop = resolve; }));
      projection.mockResolvedValueOnce({
        state: 'recording',
        steps: [{ row_id: 'c1:action', candidate_id: 'c1', ordinal: 1, status: 'accepted', is_action: true, title: '打开项目', action_kind: 'click', trace_id: 't1' }],
      }).mockResolvedValue({ state: 'stopped', steps: [] });
      const { default: Page } = await import('./RecorderPage.vue');
      const root = document.createElement('div'); document.body.appendChild(root);
      const app = createApp(Page); app.mount(root); await flush();

      root.querySelector<HTMLButtonElement>('[data-testid="stop-recording"]')!.click();
      await vi.advanceTimersByTimeAsync(1200); await flush();
      resolveStop({
        state: 'stopped',
        configuration_draft: { schema_version: 'skill-configuration-draft/v0.1', skill: { name: '未命名 SKILL', description: '请填写' }, inputs: [], secrets: [], asset_inputs: [], outputs: [], asset_outputs: [], binding_promotions: [] },
        configuration_options: { binding_locations: [], readiness: { ready: true, issues: [] } },
      });
      await flush();

      const saved = JSON.parse(sessionStorage.getItem('rpa-agent:rca_abcdefghijklmnopqrstuvwx') || '{}');
      expect(saved.creationSteps).toHaveLength(1);
      expect(saved.creationSteps[0].title).toBe('打开项目');
      app.unmount();
    } finally { vi.useRealTimers(); }
  });
});
