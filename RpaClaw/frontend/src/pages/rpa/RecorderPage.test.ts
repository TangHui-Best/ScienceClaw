// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const push = vi.fn();
const start = vi.fn();
const projection = vi.fn();
const instruction = vi.fn();
const stop = vi.fn();
const manualInput = vi.fn();
const listModels = vi.fn();
const routeQuery: Record<string, string> = {};

vi.mock('vue-router', () => ({ useRouter: () => ({ push }), useRoute: () => ({ query: routeQuery }) }));
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (value: string) => value }) }));
vi.mock('@/api/models', () => ({ listModels: (...args: unknown[]) => listModels(...args) }));
vi.mock('@/api/rpaAgent', () => ({
  startRpaAgentSession: (...args: unknown[]) => start(...args),
  getRpaAgentProjection: (...args: unknown[]) => projection(...args),
  runRpaAgentInstruction: (...args: unknown[]) => instruction(...args),
  stopRpaAgentSession: (...args: unknown[]) => stop(...args),
  dispatchRpaAgentManualInput: (...args: unknown[]) => manualInput(...args),
}));
vi.mock('@/components/SandboxPreview.vue', () => ({
  default: {
    props: ['sessionId', 'manualInputDispatcher', 'manualInputDisabled'],
    template: '<button data-testid="browser-preview" :disabled="manualInputDisabled" @click="manualInputDispatcher({ input_id: \'input_canvas_1\', kind: \'click\', x: 12, y: 34 })">{{ sessionId }}</button>',
  },
}));
vi.mock('@/components/rpa/RpaFlowGuide.vue', () => ({ default: { template: '<nav data-testid="flow-guide" />' } }));
vi.mock('@/components/rpa/RpaStepTimeline.vue', () => ({
  default: { props: ['steps'], template: '<div data-testid="timeline"><span v-for="step in steps" :key="step.id">{{ step.kind }} {{ step.executionStatus }} {{ step.title }}</span></div>' },
}));

const timelineItems = [
  {
    id: 'trace-1', kind: 'manual', ordinal: 1, title: '点击查询', capture_status: 'captured',
    execution_status: 'succeeded', replay_status: 'deterministic_ready', compile_mode: 'playwright', observations: [],
  },
  {
    id: 'ai-1', kind: 'ai_instruction', ordinal: 2, title: '获取 star 数', capture_status: 'observing',
    execution_status: 'succeeded', replay_status: 'insufficient_evidence', compile_mode: 'agent',
    observations: [{ trace_id: 'child-1', action: 'click', summary: '打开项目' }],
  },
];
const flush = async () => {
  for (let index = 0; index < 6; index += 1) await Promise.resolve();
  await nextTick();
};

describe('RecorderPage intent-first creation journey', () => {
  beforeEach(() => {
    sessionStorage.clear(); document.body.innerHTML = '';
    for (const key of Object.keys(routeQuery)) delete routeQuery[key];
    push.mockReset(); start.mockReset(); projection.mockReset(); instruction.mockReset();
    stop.mockReset(); manualInput.mockReset(); listModels.mockReset();
    start.mockResolvedValue({
      session_id: 'rca_abcdefghijklmnopqrstuvwx', state: 'recording',
      browser_session_ref: 'bhs_recording_1', page_ref: 'page-1', generation: 'gen-1',
    });
    listModels.mockResolvedValue([{ id: 'model-1', name: 'Model One', model_name: 'model-one' }]);
    projection.mockResolvedValue({ session_id: 'rca_abcdefghijklmnopqrstuvwx', recording_state: 'recording', items: timelineItems });
    instruction.mockResolvedValue({ step_id: 'ai-2', ordinal: 3, execution_status: 'queued' });
    manualInput.mockResolvedValue({ input_id: 'input_canvas_1', draft_id: 'draft-1', capture_status: 'captured' });
    stop.mockResolvedValue({
      state: 'stopped',
      configuration_draft: { schema_version: 'skill-configuration-draft/v0.1', skill: { name: '未命名 SKILL', description: '请填写' }, inputs: [], secrets: [], asset_inputs: [], outputs: [], asset_outputs: [], binding_promotions: [] },
      configuration_options: { binding_locations: [], readiness: { ready: true, issues: [] } },
    });
  });

  it('takes over a rerecord host without creating a duplicate session', async () => {
    Object.assign(routeQuery, {
      sessionId: 'rca_rerecordedabcdefghijkl', browserSessionRef: 'bhs_rerecorded_1',
      pageRef: 'page-rerecorded', generation: 'gen-rerecorded',
    });
    const { default: Page } = await import('./RecorderPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Page); app.mount(root); await flush();
    expect(start).not.toHaveBeenCalled();
    expect(root.querySelector('[data-testid="browser-preview"]')?.textContent).toContain('bhs_rerecorded_1');
    app.unmount();
  });

  afterEach(() => { document.body.innerHTML = ''; });

  it('uses the fresh recording host and renders only intent-first top-level items', async () => {
    const { default: Page } = await import('./RecorderPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Page); app.mount(root); await flush();
    expect(start).toHaveBeenCalledWith();
    expect(root.querySelector('[data-testid="recorder-left"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="recorder-center"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="recorder-right"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="browser-preview"]')?.textContent).toContain('bhs_recording_1');
    expect(root.textContent).toContain('manual succeeded 点击查询');
    expect(root.textContent).toContain('ai_instruction succeeded 获取 star 数');
    expect(root.textContent).not.toContain('Candidate');
    app.unmount();
  });

  it('routes manual input atomically and submits AI instruction with the selected model', async () => {
    const { default: Page } = await import('./RecorderPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Page); app.mount(root); await flush();
    root.querySelector<HTMLButtonElement>('[data-testid="browser-preview"]')!.click();
    await flush();
    expect(manualInput).toHaveBeenCalledWith('rca_abcdefghijklmnopqrstuvwx', {
      input_id: 'input_canvas_1', kind: 'click', x: 12, y: 34,
    });

    const urlInput = root.querySelector<HTMLInputElement>('input[name="recording-url"]')!;
    urlInput.value = 'https://github.com/trending';
    urlInput.dispatchEvent(new Event('input'));
    await nextTick();
    root.querySelector<HTMLButtonElement>('[data-testid="navigate-recording-browser"]')!.click();
    await flush();
    expect(manualInput).toHaveBeenCalledWith(
      'rca_abcdefghijklmnopqrstuvwx',
      expect.objectContaining({ kind: 'navigate', text: 'https://github.com/trending' }),
    );

    const textarea = root.querySelector<HTMLTextAreaElement>('textarea[name="agent-instruction"]')!;
    textarea.value = '打开和 skill 最相关的项目';
    textarea.dispatchEvent(new Event('input'));
    await nextTick();
    root.querySelector<HTMLButtonElement>('[data-testid="run-agent"]')!.click();
    await flush();
    expect(instruction).toHaveBeenCalledWith(
      'rca_abcdefghijklmnopqrstuvwx',
      '打开和 skill 最相关的项目',
      expect.objectContaining({ model_id: 'model-1' }),
    );
    app.unmount();
  });

  it('stops before entering configuration', async () => {
    const { default: Page } = await import('./RecorderPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Page); app.mount(root); await flush();
    root.querySelector<HTMLButtonElement>('[data-testid="stop-recording"]')!.click();
    expect(push).not.toHaveBeenCalled();
    await flush();
    expect(stop).toHaveBeenCalledWith('rca_abcdefghijklmnopqrstuvwx');
    expect(push).toHaveBeenCalledWith({ path: '/rpa/configure', query: { sessionId: 'rca_abcdefghijklmnopqrstuvwx' } });
    app.unmount();
  });
});
