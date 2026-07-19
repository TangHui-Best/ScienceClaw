import type { RecordingTimelineItem } from '@/api/rpaAgent';

export interface RpaAgentCreationStepViewModel {
  id: string;
  ordinal: number;
  kind: RecordingTimelineItem['kind'];
  title: string;
  description: string;
  label: string;
  action: string;
  captureStatus: RecordingTimelineItem['capture_status'];
  executionStatus: RecordingTimelineItem['execution_status'];
  replayStatus: RecordingTimelineItem['replay_status'];
  compileMode: RecordingTimelineItem['compile_mode'];
  observations: RecordingTimelineItem['observations'];
  isEffect: false;
  is_action: true;
  validation: { status: string; details: string };
}

const executionLabel: Record<RecordingTimelineItem['execution_status'], string> = {
  queued: '排队中', running: '执行中', succeeded: '已完成', failed: '执行失败', cancelled: '已取消',
};

export function projectRpaAgentCreationSteps(
  items: readonly RecordingTimelineItem[],
): RpaAgentCreationStepViewModel[] {
  return items.map((item) => ({
    id: item.id,
    ordinal: item.ordinal,
    kind: item.kind,
    title: item.title,
    description: item.title,
    label: item.kind === 'manual' ? '手工' : 'AI',
    action: item.kind === 'manual' ? 'manual' : 'agent',
    captureStatus: item.capture_status,
    executionStatus: item.execution_status,
    replayStatus: item.replay_status,
    compileMode: item.compile_mode,
    observations: item.observations,
    isEffect: false,
    is_action: true,
    validation: {
      status: item.replay_status,
      details: `${executionLabel[item.execution_status]} · ${item.capture_status}`,
    },
  }));
}
