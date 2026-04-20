import { describe, expect, it } from 'vitest';
import {
  getLegacyRpaSteps,
  mapRpaConfigureDisplaySteps,
} from './rpaConfigureTimeline';

describe('rpaConfigureTimeline', () => {
  it('uses accepted traces as configure-page display steps when trace-first data exists', () => {
    const session = {
      steps: [
        {
          id: 'legacy-1',
          action: 'click',
          description: 'legacy click should only remain for parameterization',
        },
      ],
      traces: [
        {
          trace_id: 'trace-ai',
          trace_type: 'ai_operation',
          source: 'ai',
          description: 'Open the most Python-related project',
          user_instruction: '打开和python最相关的项目',
          output_key: 'selected_project',
          after_page: { url: 'https://github.com/openai/openai-agents-python' },
          accepted: true,
        },
        {
          trace_id: 'trace-manual',
          trace_type: 'manual_action',
          source: 'record',
          action: 'click',
          description: '点击 link("Pull requests")',
          locator_candidates: [
            {
              selected: true,
              locator: { method: 'role', role: 'link', name: 'Pull requests' },
            },
          ],
          after_page: { url: 'https://github.com/openai/openai-agents-python/pulls' },
          accepted: true,
        },
      ],
    };

    const displaySteps = mapRpaConfigureDisplaySteps(session);

    expect(displaySteps).toHaveLength(2);
    expect(displaySteps[0]).toMatchObject({
      id: 'trace-ai',
      action: 'ai_operation',
      description: 'Open the most Python-related project',
      source: 'ai',
      url: 'https://github.com/openai/openai-agents-python',
      validation: { status: 'ok', details: 'AI Trace' },
    });
    expect(displaySteps[1].target).toEqual({ method: 'role', role: 'link', name: 'Pull requests' });
  });

  it('keeps legacy steps available separately for fill/select parameterization', () => {
    const session = {
      steps: [
        { id: 'fill-1', action: 'fill', value: 'Alice', sensitive: false },
      ],
      traces: [
        {
          trace_id: 'trace-fill',
          trace_type: 'dataflow_fill',
          description: 'Dataflow fill',
        },
      ],
    };

    expect(mapRpaConfigureDisplaySteps(session)).toHaveLength(1);
    expect(getLegacyRpaSteps(session)).toEqual(session.steps);
  });

  it('falls back to legacy steps when no accepted traces are present', () => {
    const session = {
      steps: [
        { id: 'click-1', action: 'click', description: 'Click search' },
      ],
      traces: [],
    };

    expect(mapRpaConfigureDisplaySteps(session)).toEqual(session.steps);
  });
});
