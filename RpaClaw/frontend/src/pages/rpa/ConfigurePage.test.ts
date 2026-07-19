// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { saveCreationSnapshot } from '@/utils/rpaAgentSkillConfiguration';

const push = vi.fn(); const configure = vi.fn(); const compile = vi.fn();
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { sessionId: 'rca_abcdefghijklmnopqrstuvwx' } }), useRouter: () => ({ push }) }));
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (value: string) => value }) }));
vi.mock('@/api/rpaAgent', () => ({
  configureRpaAgentSkill: (...args: unknown[]) => configure(...args),
  compileRpaAgentSkill: (...args: unknown[]) => compile(...args),
}));
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await nextTick(); };

describe('ConfigurePage greenfield configuration', () => {
  beforeEach(() => {
    sessionStorage.clear(); document.body.innerHTML = ''; push.mockReset(); configure.mockReset(); compile.mockReset();
    push.mockResolvedValue(undefined);
    saveCreationSnapshot({
      sessionId: 'rca_abcdefghijklmnopqrstuvwx', browserSessionRef: 'browser-host-1',
      configurationDraft: {
        schema_version: 'skill-configuration-draft/v0.1', skill: { name: '未命名 SKILL', description: '请填写' }, inputs: [], secrets: [],
        asset_inputs: [{ ref: 'source_asset', title: '源文件', required: true }],
        outputs: [{ name: 'order_no', title: '订单号', variable_ref: '采购订单.订单号', value_type: 'string' }],
        asset_outputs: [{ name: 'result_asset', title: '结果文件', asset_ref: 'acceptance_result' }], binding_promotions: [],
      },
      bindingLocations: [
        { trace_id: 'trace-1', binding_name: 'value', direction: 'input', kind: 'literal', sensitive: true },
        { trace_id: 'trace-2', binding_name: 'value', direction: 'input', kind: 'literal', sensitive: false },
      ],
    });
    configure.mockResolvedValue({ state: 'configured' });
    compile.mockResolvedValue({ state: 'compiled', artifact_hash: 'artifact-hash', artifact_files: ['SKILL.md', 'skill.manifest.json', 'skill.py', 'browser_segment.py'] });
  });

  it('uses exact binding location, configures then compiles exactly once and stores no secret value', async () => {
    const { default: Page } = await import('./ConfigurePage.vue');
    const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();
    expect(root.querySelector('[data-testid="configure-flow-guide"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="configure-steps"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="configure-skill-panel"]')).not.toBeNull();
    expect(root.textContent).toContain('录制步骤');
    expect(root.textContent).toContain('技能信息');
    expect(root.textContent).toContain('可配置参数');
    expect(root.textContent).not.toContain('trace_id + binding_name');
    const name = root.querySelector<HTMLInputElement>('input[name="skill-name"]')!; name.value = '采购验收'; name.dispatchEvent(new Event('input'));
    expect(root.querySelector('input[name="secret-value"]')).toBeNull();
    root.querySelectorAll<HTMLButtonElement>('[data-testid="promote-binding"]')[1].click(); await nextTick();
    root.querySelectorAll<HTMLButtonElement>('[data-testid="promote-secret"]')[0].click();
    await nextTick();
    const inputRow = root.querySelector<HTMLInputElement>('input[aria-label="Input ref"]')!.parentElement!;
    const inputRef = inputRow.querySelector<HTMLInputElement>('input[aria-label="Input ref"]')!;
    inputRef.value = 'purchase_order'; inputRef.dispatchEvent(new Event('change')); await nextTick();
    let refreshedRow = root.querySelector<HTMLInputElement>('input[aria-label="Input ref"]')!.parentElement!;
    const type = refreshedRow.querySelector<HTMLSelectElement>('select')!; type.value = 'number'; type.dispatchEvent(new Event('change')); await nextTick();
    refreshedRow = root.querySelector<HTMLInputElement>('input[aria-label="Input ref"]')!.parentElement!;
    const checkboxes = refreshedRow.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    checkboxes[1].checked = true; checkboxes[1].dispatchEvent(new Event('change')); await nextTick();
    const numberDefault = root.querySelector<HTMLInputElement>('input[type="number"]')!; numberDefault.value = '0'; numberDefault.dispatchEvent(new Event('input')); await nextTick();
    root.querySelector<HTMLButtonElement>('[data-testid="compile-skill"]')!.click(); await flush();

    expect(configure).toHaveBeenCalledTimes(1); expect(compile).toHaveBeenCalledTimes(1);
    const payload = configure.mock.calls[0][1];
    expect(payload.binding_promotions).toEqual(expect.arrayContaining([
      { trace_id: 'trace-2', binding_name: 'value', to_kind: 'skill_input', ref: 'purchase_order' },
      { trace_id: 'trace-1', binding_name: 'value', to_kind: 'secret', ref: 'value_trace_1_secret' },
    ]));
    expect(payload.secrets).toHaveLength(1); expect(payload.outputs).toHaveLength(1);
    expect(payload.inputs[0]).toEqual(expect.objectContaining({ ref: 'purchase_order', value_type: 'number', default: 0 }));
    expect(payload.asset_inputs).toHaveLength(1); expect(payload.asset_outputs).toHaveLength(1);
    expect(sessionStorage.getItem('rpa-agent:rca_abcdefghijklmnopqrstuvwx')).not.toContain('secret-value');
    expect(push).toHaveBeenCalledWith({ path: '/rpa/test', query: { sessionId: 'rca_abcdefghijklmnopqrstuvwx' } });
    app.unmount();
  });

  it('persists configured state and retries only compile after a compile failure', async () => {
    compile.mockRejectedValueOnce(new Error('compile failed'))
      .mockResolvedValueOnce({ state: 'compiled', artifact_hash: 'artifact-hash', artifact_files: ['SKILL.md', 'skill.manifest.json', 'skill.py', 'browser_segment.py'] });
    const { default: Page } = await import('./ConfigurePage.vue');
    const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();

    const button = root.querySelector<HTMLButtonElement>('[data-testid="compile-skill"]')!;
    button.click(); await flush();
    expect(configure).toHaveBeenCalledTimes(1); expect(compile).toHaveBeenCalledTimes(1);
    expect(JSON.parse(sessionStorage.getItem('rpa-agent:rca_abcdefghijklmnopqrstuvwx')!)).toMatchObject({ configurationState: 'configured' });
    expect(push).not.toHaveBeenCalled();

    app.unmount();
    const retryRoot = document.createElement('div'); document.body.appendChild(retryRoot); const retryApp = createApp(Page); retryApp.mount(retryRoot); await flush();
    retryRoot.querySelector<HTMLButtonElement>('[data-testid="compile-skill"]')!.click(); await flush();
    expect(configure).toHaveBeenCalledTimes(1); expect(compile).toHaveBeenCalledTimes(2);
    expect(JSON.parse(sessionStorage.getItem('rpa-agent:rca_abcdefghijklmnopqrstuvwx')!)).toMatchObject({ configurationState: 'compiled', artifactHash: 'artifact-hash' });
    expect(push).toHaveBeenCalledTimes(1);
    retryApp.unmount();
  });

  it('reloads a compiled snapshot without calling configuration or compile again', async () => {
    saveCreationSnapshot({
      sessionId: 'rca_abcdefghijklmnopqrstuvwx', browserSessionRef: 'browser-host-1', configurationState: 'compiled',
      artifactHash: 'artifact-hash', artifactFiles: ['SKILL.md', 'skill.manifest.json', 'skill.py', 'browser_segment.py'],
      configurationDraft: {
        schema_version: 'skill-configuration-draft/v0.1', skill: { name: '采购验收', description: '测试' },
        inputs: [], secrets: [], asset_inputs: [], outputs: [], asset_outputs: [], binding_promotions: [],
      },
    });
    const { default: Page } = await import('./ConfigurePage.vue');
    const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();
    root.querySelector<HTMLButtonElement>('[data-testid="compile-skill"]')!.click(); await flush();
    expect(configure).not.toHaveBeenCalled(); expect(compile).not.toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith({ path: '/rpa/test', query: { sessionId: 'rca_abcdefghijklmnopqrstuvwx' } });
    app.unmount();
  });

  it('keeps a compiled artifact after navigation failure and allows retrying navigation only', async () => {
    push.mockRejectedValueOnce(new Error('navigation failed')).mockResolvedValueOnce(undefined);
    const { default: Page } = await import('./ConfigurePage.vue');
    const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();
    const button = root.querySelector<HTMLButtonElement>('[data-testid="compile-skill"]')!;
    button.click(); await flush();
    expect(JSON.parse(sessionStorage.getItem('rpa-agent:rca_abcdefghijklmnopqrstuvwx')!)).toMatchObject({ configurationState: 'compiled', artifactHash: 'artifact-hash' });
    expect(root.textContent).toContain('产物已生成');
    const retryButton = root.querySelector<HTMLButtonElement>('[data-testid="compile-skill"]')!;
    await vi.waitFor(() => expect(retryButton.disabled).toBe(false)); retryButton.click(); await flush();
    expect(configure).toHaveBeenCalledTimes(1); expect(compile).toHaveBeenCalledTimes(1); expect(push).toHaveBeenCalledTimes(2);
    app.unmount();
  });

  it('restores an invalid rename in the DOM and blocks compilation until corrected', async () => {
    const { default: Page } = await import('./ConfigurePage.vue');
    const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();
    root.querySelectorAll<HTMLButtonElement>('[data-testid="promote-binding"]')[0].click(); await nextTick();
    const input = root.querySelector<HTMLInputElement>('input[aria-label="Input ref"]')!;
    const original = input.value; input.value = ''; input.dispatchEvent(new Event('change')); await nextTick();
    expect(input.value).toBe(original);
    expect(root.querySelector<HTMLButtonElement>('[data-testid="compile-skill"]')!.disabled).toBe(true);
    input.dispatchEvent(new Event('change')); await nextTick();
    expect(root.querySelector<HTMLButtonElement>('[data-testid="compile-skill"]')!.disabled).toBe(false);
    app.unmount();
  });
});
