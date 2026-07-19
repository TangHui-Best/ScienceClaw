import { describe, expect, it } from 'vitest';
import { projectRpaAgentCreationSteps } from './rpaAgentCreationProjection';

describe('RPA Agent intent-first projection', () => {
  it('keeps only top-level manual traces and AI instructions', () => {
    const rows = projectRpaAgentCreationSteps([
      {
        id: 'trace-1', kind: 'manual', ordinal: 1, title: '点击查询',
        capture_status: 'captured', execution_status: 'succeeded',
        replay_status: 'deterministic_ready', compile_mode: 'playwright', observations: [],
      },
      {
        id: 'ai-1', kind: 'ai_instruction', ordinal: 2, title: '获取 star 数',
        capture_status: 'observing', execution_status: 'running',
        replay_status: 'pending', compile_mode: null,
        observations: [{ trace_id: 'trace-child', action: 'click', summary: '打开项目' }],
      },
    ]);

    expect(rows.map((row) => [row.id, row.kind, row.executionStatus])).toEqual([
      ['trace-1', 'manual', 'succeeded'],
      ['ai-1', 'ai_instruction', 'running'],
    ]);
    expect(rows[1].observations).toHaveLength(1);
    expect(rows.every((row) => row.isEffect === false)).toBe(true);
  });
});
