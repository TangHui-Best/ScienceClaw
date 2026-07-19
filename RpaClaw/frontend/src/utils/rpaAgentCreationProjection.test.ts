import { describe, expect, it } from 'vitest';
import { projectRpaAgentCreationSteps } from './rpaAgentCreationProjection';

describe('RPA Agent creation projection', () => {
  it('keeps action states and represents effects as children, not actions', () => {
    const rows = projectRpaAgentCreationSteps([
      { row_id: 'c1:action', candidate_id: 'c1', ordinal: 1, status: 'pending', is_action: true, title: '等待结算', action_kind: 'click' },
      { row_id: 'c2:action', candidate_id: 'c2', ordinal: 2, status: 'accepted', is_action: true, title: '打开验收', action_kind: 'click', trace_id: 't2', sequence: 2 },
      { row_id: 't2:effect:0', candidate_id: 'c2', ordinal: 2, status: 'effect', is_action: false, title: '打开新页面', effect_kind: 'new_page', parent_trace_id: 't2' },
      { row_id: 'c3:action', candidate_id: 'c3', ordinal: 3, status: 'rejected', is_action: true, title: '录制失败', diagnostic_message: '目标不明确' },
    ]);

    expect(rows.map((row) => [row.id, row.status, row.parentId, row.isEffect])).toEqual([
      ['c1:action', 'pending', null, false],
      ['c2:action', 'accepted', null, false],
      ['t2:effect:0', 'effect', 't2', true],
      ['c3:action', 'rejected', null, false],
    ]);
    expect(rows.filter((row) => !row.isEffect)).toHaveLength(3);
  });
});
