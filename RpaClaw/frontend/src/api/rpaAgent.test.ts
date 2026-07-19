import { beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
vi.mock('./client', () => ({ apiClient: { get, post, put } }));

describe('rpaAgent API', () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue({ data: {} });
    post.mockReset().mockResolvedValue({ data: {} });
    put.mockReset().mockResolvedValue({ data: {} });
  });

  it('starts a factory-owned recording session and uses the greenfield lifecycle', async () => {
    const api = await import('./rpaAgent');
    const sessionId = 'rca_abcdefghijklmnopqrstuvwx';
    await api.startRpaAgentSession();
    await api.dispatchRpaAgentManualInput(sessionId, {
      input_id: 'input_canvas_1', kind: 'click', x: 12, y: 34,
    });
    await api.getRpaAgentProjection(sessionId);
    await api.stopRpaAgentSession(sessionId);
    await api.configureRpaAgentSkill(sessionId, {
      schema_version: 'skill-configuration-draft/v0.1',
      skill: { name: 'Skill', description: 'Description' },
      inputs: [], secrets: [], asset_inputs: [], outputs: [], asset_outputs: [], binding_promotions: [],
    });
    await api.compileRpaAgentSkill(sessionId);
    await api.testRpaAgentSkill(sessionId, { inputs: {}, secrets: {}, data_assets: {} });
    await api.saveRpaAgentSkill(sessionId);

    expect(post).toHaveBeenNthCalledWith(1, '/rpa-agent/sessions', {});
    expect(get).toHaveBeenCalledWith(`/rpa-agent/sessions/${sessionId}/projection`);
    expect(post.mock.calls.map(([url]) => url)).toEqual([
      '/rpa-agent/sessions',
      `/rpa-agent/sessions/${sessionId}/manual-inputs`,
      `/rpa-agent/sessions/${sessionId}/stop`,
      `/rpa-agent/sessions/${sessionId}/compile`,
      `/rpa-agent/sessions/${sessionId}/test-run`,
      `/rpa-agent/sessions/${sessionId}/save`,
    ]);
    expect(post).toHaveBeenNthCalledWith(
      5,
      `/rpa-agent/sessions/${sessionId}/test-run`,
      { inputs: {}, secrets: {}, data_assets: {} },
      { timeout: api.RPA_AGENT_TEST_RUN_TIMEOUT_MS },
    );
    expect(JSON.stringify([...get.mock.calls, ...post.mock.calls, ...put.mock.calls])).not.toContain('/rpa/session');
  });

  it('submits the original instruction with an explicit idempotency key and model policy', async () => {
    const api = await import('./rpaAgent');
    const sessionId = 'rca_abcdefghijklmnopqrstuvwx';
    await api.runRpaAgentInstruction(sessionId, '获取 star 数', {
      model_id: 'model-1', business_terms: ['GitHub'], required_variable_refs: [],
      allowed_inputs: {}, allowed_secret_names: [], allowed_data_assets: {}, page_aliases: {},
    }, 'agent-key-0000001');

    expect(post).toHaveBeenCalledWith(
      `/rpa-agent/sessions/${sessionId}/agent-instructions`,
      {
        instruction: '获取 star 数', model_id: 'model-1', business_terms: ['GitHub'],
        required_variable_refs: [], allowed_inputs: {}, allowed_secret_names: [],
        allowed_data_assets: {}, page_aliases: {},
      },
      { headers: { 'Idempotency-Key': 'agent-key-0000001' } },
    );
  });
});
