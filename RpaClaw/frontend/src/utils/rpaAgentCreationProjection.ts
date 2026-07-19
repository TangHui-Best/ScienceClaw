import type { CreationProjectionRow } from '@/api/rpaAgent';

export interface RpaAgentCreationStepViewModel {
  id: string;
  candidateId: string;
  status: CreationProjectionRow['status'];
  title: string;
  description: string;
  label: string;
  action: string;
  traceId: string | null;
  parentId: string | null;
  isEffect: boolean;
  is_action: boolean;
  validation: { status: string; details: string };
}

export function projectRpaAgentCreationSteps(rows: readonly CreationProjectionRow[]): RpaAgentCreationStepViewModel[] {
  return rows.map((row) => {
    const isEffect = row.status === 'effect' || !row.is_action;
    const details = row.diagnostic_message || row.diagnostic_code || '';
    return {
      id: row.row_id,
      candidateId: row.candidate_id,
      status: row.status,
      title: row.title,
      description: row.title,
      label: isEffect ? (row.effect_kind || 'effect') : (row.action_kind || 'action'),
      action: isEffect ? 'effect' : (row.action_kind || 'action'),
      traceId: row.trace_id || null,
      parentId: row.parent_trace_id || null,
      isEffect,
      is_action: !isEffect,
      validation: { status: row.status, details },
    };
  });
}
