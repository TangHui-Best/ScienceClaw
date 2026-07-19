import { beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();

vi.mock('./client', () => ({ apiClient: { get, post, put } }));

describe('rpaAgent API', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    put.mockReset();
    get.mockResolvedValue({ data: {} });
    post.mockResolvedValue({ data: {} });
    put.mockResolvedValue({ data: {} });
  });

  it('uses only the greenfield rpa-agent session endpoints', async () => {
    const api = await import('./rpaAgent');
    await api.startRpaAgentSession('browser-host-1');
    await api.reserveRpaAgentManualAction('rca_abcdefghijklmnopqrstuvwx', { candidate_id: 'candidate-1', page_runtime_ref: 'page-1', frame_runtime_ref: 'frame-1' });
    await api.recordRpaAgentManualEvent('rca_abcdefghijklmnopqrstuvwx', { reservation_token: 'x'.repeat(32), kind: 'click' });
    await api.dispatchRpaAgentManualInput('rca_abcdefghijklmnopqrstuvwx', { input_id: 'input_canvas_1', kind: 'click', x: 12, y: 34 });
    await api.getRpaAgentProjection('rca_abcdefghijklmnopqrstuvwx');
    await api.stopRpaAgentSession('rca_abcdefghijklmnopqrstuvwx');
    await api.configureRpaAgentSkill('rca_abcdefghijklmnopqrstuvwx', { schema_version: 'skill-configuration-draft/v0.1', skill: { name: 'Skill', description: 'Description' }, inputs: [], secrets: [], asset_inputs: [], outputs: [], asset_outputs: [], binding_promotions: [] });
    await api.compileRpaAgentSkill('rca_abcdefghijklmnopqrstuvwx');
    await api.testRpaAgentSkill('rca_abcdefghijklmnopqrstuvwx', { inputs: {}, secrets: {}, data_assets: {} });
    await api.saveRpaAgentSkill('rca_abcdefghijklmnopqrstuvwx');

    expect(post).toHaveBeenNthCalledWith(1, '/rpa-agent/sessions', { browser_session_ref: 'browser-host-1' });
    expect(get).toHaveBeenCalledWith('/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/projection');
    expect(post.mock.calls.map(([url]) => url)).toEqual([
      '/rpa-agent/sessions',
      '/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/manual-reservations',
      '/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/manual-events',
      '/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/manual-inputs',
      '/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/stop',
      '/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/compile',
      '/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/test-run',
      '/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/save',
    ]);
    expect(put).toHaveBeenCalledWith('/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/configuration', expect.objectContaining({ schema_version: 'skill-configuration-draft/v0.1' }));
    expect(JSON.stringify([...get.mock.calls, ...post.mock.calls, ...put.mock.calls])).not.toContain('/rpa/session');
  });

  it('sends only the explicitly supplied instruction whitelist context', async () => {
    const api = await import('./rpaAgent');
    await api.runRpaAgentInstruction('rca_abcdefghijklmnopqrstuvwx', '提取订单', {
      business_terms: ['采购订单'], required_variable_refs: ['采购订单.订单号'],
      allowed_inputs: { profile: '当前回放配置' }, allowed_secret_names: ['erp_password'],
      allowed_data_assets: {}, page_aliases: { system_a: '采购订单系统' },
    });
    expect(post).toHaveBeenCalledWith('/rpa-agent/sessions/rca_abcdefghijklmnopqrstuvwx/agent-instructions', {
      instruction: '提取订单', business_terms: ['采购订单'], required_variable_refs: ['采购订单.订单号'],
      allowed_inputs: { profile: '当前回放配置' }, allowed_secret_names: ['erp_password'],
      allowed_data_assets: {}, page_aliases: { system_a: '采购订单系统' },
    });
  });
});
