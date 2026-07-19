// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from 'vitest';
import {
  applyBindingPromotion,
  promoteBindingLocation,
  renamePromotedBindingRef,
  setDraftInputDefault,
  loadCreationSnapshot,
  saveCreationSnapshot,
  type SkillConfigurationDraft,
} from './rpaAgentSkillConfiguration';

const draft = (): SkillConfigurationDraft => ({
  schema_version: 'skill-configuration-draft/v0.1',
  skill: { name: '采购验收', description: '登记采购验收' },
  inputs: [], secrets: [], asset_inputs: [], outputs: [], asset_outputs: [], binding_promotions: [],
});

describe('RPA Agent skill configuration', () => {
  beforeEach(() => sessionStorage.clear());

  it('promotes by the exact trace_id + binding_name key even when recorded values match', () => {
    const result = applyBindingPromotion(draft(), {
      trace_id: 'trace-a', binding_name: 'value', to_kind: 'skill_input', ref: 'order_a',
    });
    const second = applyBindingPromotion(result, {
      trace_id: 'trace-b', binding_name: 'value', to_kind: 'skill_input', ref: 'order_b',
    });
    expect(second.binding_promotions).toEqual([
      { trace_id: 'trace-a', binding_name: 'value', to_kind: 'skill_input', ref: 'order_a' },
      { trace_id: 'trace-b', binding_name: 'value', to_kind: 'skill_input', ref: 'order_b' },
    ]);
  });

  it('creates stable unique refs for same-named bindings and atomically switches Input to Secret', () => {
    const first = promoteBindingLocation(draft(), { trace_id: 'trace-one', binding_name: 'value' }, 'skill_input');
    const second = promoteBindingLocation(first, { trace_id: 'trace-two', binding_name: 'value' }, 'skill_input');
    expect(second.inputs.map((item) => item.ref)).toEqual(['value_trace_one_input', 'value_trace_two_input']);
    const switched = promoteBindingLocation(second, { trace_id: 'trace-one', binding_name: 'value' }, 'secret');
    expect(switched.inputs.map((item) => item.ref)).toEqual(['value_trace_two_input']);
    expect(switched.secrets.map((item) => item.ref)).toEqual(['value_trace_one_secret']);
    expect(switched.binding_promotions.find((item) => item.trace_id === 'trace-one')).toEqual({ trace_id: 'trace-one', binding_name: 'value', to_kind: 'secret', ref: 'value_trace_one_secret' });
  });

  it('removes a renamed declaration when switching Input to Secret', () => {
    const promoted = promoteBindingLocation(draft(), { trace_id: 'trace-one', binding_name: 'value' }, 'skill_input');
    const renamed = renamePromotedBindingRef(promoted, 'skill_input', 'value_trace_one_input', 'purchase_order');
    const switched = promoteBindingLocation(renamed, { trace_id: 'trace-one', binding_name: 'value' }, 'secret');

    expect(switched.inputs).toEqual([]);
    expect(switched.secrets.map((item) => item.ref)).toEqual(['value_trace_one_secret']);
    expect(switched.binding_promotions).toEqual([
      { trace_id: 'trace-one', binding_name: 'value', to_kind: 'secret', ref: 'value_trace_one_secret' },
    ]);
  });

  it('refuses empty or duplicate refs when renaming promoted declarations', () => {
    const first = promoteBindingLocation(draft(), { trace_id: 'trace-one', binding_name: 'value' }, 'skill_input');
    const second = promoteBindingLocation(first, { trace_id: 'trace-two', binding_name: 'value' }, 'skill_input');

    expect(() => renamePromotedBindingRef(second, 'skill_input', 'value_trace_one_input', ''))
      .toThrow('configuration.ref_required');
    expect(() => renamePromotedBindingRef(second, 'skill_input', 'value_trace_one_input', 'value_trace_two_input'))
      .toThrow('configuration.ref_duplicate');
  });

  it('keeps unset distinct from typed number 0 and boolean false defaults', () => {
    const configured: SkillConfigurationDraft = { ...draft(), inputs: [
      { ref: 'count', title: '数量', required: true, value_type: 'number' },
      { ref: 'enabled', title: '启用', required: false, value_type: 'boolean' },
    ] };
    const withNumber = setDraftInputDefault(configured, 'count', true, '0');
    const withBoolean = setDraftInputDefault(withNumber, 'enabled', true, 'false');
    expect(withBoolean.inputs).toEqual([
      { ref: 'count', title: '数量', required: true, value_type: 'number', default: 0 },
      { ref: 'enabled', title: '启用', required: false, value_type: 'boolean', default: false },
    ]);
    expect(setDraftInputDefault(withBoolean, 'count', false).inputs[0]).not.toHaveProperty('default');
  });

  it('persists routing snapshots for the matching session without secret plaintext', () => {
    saveCreationSnapshot({
      sessionId: 'rca_abcdefghijklmnopqrstuvwx',
      browserSessionRef: 'browser-host-1',
      artifactHash: 'hash-1',
      artifactFiles: ['SKILL.md', 'skill.manifest.json', 'skill.py', 'browser_segment.py'],
      configurationDraft: { ...draft(), secrets: [{ ref: 'portal_password', title: '密码', required: true }] },
      ...({ secretValues: { portal_password: 'DO_NOT_PERSIST' } } as Record<string, unknown>),
    } as Parameters<typeof saveCreationSnapshot>[0]);
    expect(sessionStorage.getItem('rpa-agent:rca_abcdefghijklmnopqrstuvwx')).not.toContain('DO_NOT_PERSIST');
    expect(loadCreationSnapshot('rca_abcdefghijklmnopqrstuvwx')?.artifactHash).toBe('hash-1');
    expect(loadCreationSnapshot('rca_wrong')).toBeNull();
  });
});
