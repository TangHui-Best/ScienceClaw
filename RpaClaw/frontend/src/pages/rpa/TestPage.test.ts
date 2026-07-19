// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { saveCreationSnapshot } from '@/utils/rpaAgentSkillConfiguration';

const testRun = vi.fn(); const save = vi.fn(); const compile = vi.fn();
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { sessionId: 'rca_abcdefghijklmnopqrstuvwx' } }), useRouter: () => ({ push: vi.fn() }) }));
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (value: string) => value }) }));
vi.mock('@/api/rpaAgent', () => ({
  testRpaAgentSkill: (...args: unknown[]) => testRun(...args),
  saveRpaAgentSkill: (...args: unknown[]) => save(...args),
  compileRpaAgentSkill: (...args: unknown[]) => compile(...args),
}));
vi.mock('@/components/SandboxPreview.vue', () => ({ default: { props: ['sessionId'], template: '<div data-testid="test-browser">{{ sessionId }}</div>' } }));
const flush = async () => { for (let index = 0; index < 6; index += 1) await Promise.resolve(); await nextTick(); };

describe('TestPage compiled artifact replay', () => {
  beforeEach(() => {
    sessionStorage.clear(); document.body.innerHTML = ''; testRun.mockReset(); save.mockReset(); compile.mockReset();
    saveCreationSnapshot({
      sessionId: 'rca_abcdefghijklmnopqrstuvwx', browserSessionRef: 'browser-host-1', artifactHash: 'artifact-hash', artifactFiles: ['SKILL.md', 'skill.manifest.json', 'skill.py', 'browser_segment.py'],
      configurationDraft: { schema_version: 'skill-configuration-draft/v0.1', skill: { name: '采购验收', description: '测试' }, inputs: [], secrets: [{ ref: 'erp_password', title: 'ERP 密码', required: true }], asset_inputs: [{ ref: 'source_file', title: '源文件', required: true }, { ref: 'optional_file', title: '可选文件', required: false }], outputs: [], asset_outputs: [], binding_promotions: [] },
    });
  });

  it('never recompiles, shows exact failed step and prevents save after a failed run', async () => {
    testRun.mockResolvedValue({ state: 'compiled', artifact_hash: 'artifact-hash', run_result: { status: 'failed', steps: [{ trace_id: 'trace-1', sequence: 1, status: 'succeeded' }], failed_step: { trace_id: 'trace-9', sequence: 9, phase: 'action' }, error: 'locator ambiguous' } });
    const { default: Page } = await import('./TestPage.vue'); const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();
    const secret = root.querySelector<HTMLInputElement>('input[name="secret-erp_password"]')!; secret.value = 'MEMORY-ONLY'; secret.dispatchEvent(new Event('input'));
    root.querySelector<HTMLButtonElement>('[data-testid="test-run"]')!.click(); await flush();
    expect(testRun).not.toHaveBeenCalled(); expect(root.textContent).toContain('source_file');
    const asset = root.querySelector<HTMLInputElement>('input[name="asset-source_file"]')!; asset.value = 'asset://source.csv'; asset.dispatchEvent(new Event('input'));
    root.querySelector<HTMLButtonElement>('[data-testid="test-run"]')!.click(); await flush();
    expect(testRun.mock.calls[0][1].secrets).toEqual({ erp_password: 'MEMORY-ONLY' });
    expect(testRun.mock.calls[0][1].data_assets).toEqual({ source_file: 'asset://source.csv' });
    expect(secret.value).toBe('');
    expect(compile).not.toHaveBeenCalled(); expect(root.textContent).toContain('trace-1'); expect(root.textContent).toContain('trace-9'); expect(root.textContent).toContain('locator ambiguous');
    expect(root.querySelector<HTMLButtonElement>('[data-testid="save-skill"]')!.disabled).toBe(true);
    expect(root.querySelector<HTMLButtonElement>('[data-testid="test-run"]')!.disabled).toBe(false);
    app.unmount();
  });

  it('disables rerun after success, restores tested state after reload, and saves only once', async () => {
    testRun.mockResolvedValue({ state: 'tested', artifact_hash: 'artifact-hash', run_result: { status: 'succeeded', steps: [] } }); save.mockResolvedValue({ state: 'saved', skill_ref: 'skill-1', artifact_hash: 'artifact-hash' });
    const { default: Page } = await import('./TestPage.vue'); const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await flush();
    const asset = root.querySelector<HTMLInputElement>('input[name="asset-source_file"]')!; asset.value = 'asset://source.csv'; asset.dispatchEvent(new Event('input'));
    const optional = root.querySelector<HTMLInputElement>('input[name="asset-optional_file"]')!; optional.value = '   '; optional.dispatchEvent(new Event('input'));
    const runButton = root.querySelector<HTMLButtonElement>('[data-testid="test-run"]')!; runButton.click(); await flush();
    expect(testRun).toHaveBeenCalledTimes(1); expect(testRun.mock.calls[0][1].data_assets).toEqual({ source_file: 'asset://source.csv' });
    expect(runButton.disabled).toBe(true); runButton.click(); await flush(); expect(testRun).toHaveBeenCalledTimes(1);
    expect(JSON.parse(sessionStorage.getItem('rpa-agent:rca_abcdefghijklmnopqrstuvwx')!)).toMatchObject({ testPassed: true });
    app.unmount();

    const reloadRoot = document.createElement('div'); document.body.appendChild(reloadRoot); const reloadApp = createApp(Page); reloadApp.mount(reloadRoot); await flush();
    expect(reloadRoot.querySelector<HTMLButtonElement>('[data-testid="test-run"]')!.disabled).toBe(true);
    const saveButton = reloadRoot.querySelector<HTMLButtonElement>('[data-testid="save-skill"]')!; expect(saveButton.disabled).toBe(false); saveButton.click(); await flush();
    expect(save).toHaveBeenCalledWith('rca_abcdefghijklmnopqrstuvwx'); expect(compile).not.toHaveBeenCalled();
    expect(JSON.parse(sessionStorage.getItem('rpa-agent:rca_abcdefghijklmnopqrstuvwx')!)).toMatchObject({ savedRef: 'skill-1', testPassed: true });
    expect(saveButton.disabled).toBe(true); saveButton.click(); await flush(); expect(save).toHaveBeenCalledTimes(1);
    reloadApp.unmount();
  });
});
