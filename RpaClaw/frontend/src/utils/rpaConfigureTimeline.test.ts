import { describe, expect, it } from 'vitest';
import {
  getLegacyRpaSteps,
  getManualRecordingDiagnostics,
  getRpaSessionWithTimeline,
  hasRpaTimelineProjection,
  hasManualRecordingDiagnostics,
  isRpaTimelineStepDeletable,
  mapRpaConfigureDisplaySteps,
} from './rpaConfigureTimeline';

describe('rpaConfigureTimeline', () => {
  it('deduplicates recorded actions and their derived manual traces', () => {
    const session = {
      steps: [
        {
          id: 'step-search',
          action: 'click',
          description: 'legacy click should only remain for parameterization',
        },
      ],
      traces: [
        {
          trace_id: 'trace-step-search',
          trace_type: 'manual_action',
          source: 'manual',
          action: 'click',
          description: 'derived manual trace should not duplicate recorded action',
        },
      ],
      recorded_actions: [
        {
          step_id: 'step-search',
          action_kind: 'click',
          description: 'click button("Search")',
          target: { method: 'role', role: 'button', name: 'Search' },
          validation: { status: 'ok' },
          page_state: { url: 'https://example.test/search' },
        },
      ],
    };

    const displaySteps = mapRpaConfigureDisplaySteps(session);

    expect(displaySteps).toHaveLength(1);
    expect(displaySteps[0]).toMatchObject({
      id: 'step-search',
      stepId: 'step-search',
      traceId: 'trace-step-search',
      action: 'click',
      description: 'click button("Search")',
      source: 'record',
      url: 'https://example.test/search',
      validation: { status: 'ok', details: 'Accepted manual action' },
    });
    expect(displaySteps[0].target).toEqual({ method: 'role', role: 'button', name: 'Search' });
  });

  it('keeps AI traces when recorded actions replace manual traces', () => {
    const session = {
      steps: [
        {
          id: 'step-search',
          action: 'click',
          description: 'legacy click should only remain for parameterization',
        },
      ],
      traces: [
        {
          trace_id: 'trace-step-search',
          trace_type: 'manual_action',
          source: 'manual',
          action: 'click',
          description: 'legacy manual trace',
        },
        {
          trace_id: 'trace-ai-select',
          trace_type: 'ai_operation',
          source: 'ai',
          user_instruction: 'click the first project',
          description: 'Click first project',
          after_page: { url: 'https://github.com/example/repo' },
          ai_execution: { code: 'async def run(page, results):\n    return {}' },
        },
      ],
      recorded_actions: [
        {
          step_id: 'step-search',
          action_kind: 'click',
          description: 'click button("Search")',
          target: { method: 'role', role: 'button', name: 'Search' },
          validation: { status: 'ok' },
          page_state: { url: 'https://example.test/search' },
        },
      ],
    };

    const displaySteps = mapRpaConfigureDisplaySteps(session);

    expect(displaySteps.map((step) => step.description)).toEqual([
      'click button("Search")',
      'Click first project',
    ]);
    expect(displaySteps.map((step) => step.source)).toEqual(['record', 'ai']);
    expect(displaySteps[1]).toMatchObject({
      id: 'trace-ai-select',
      traceId: 'trace-ai-select',
      action: 'ai_operation',
      url: 'https://github.com/example/repo',
      validation: { status: 'ok', details: 'AI Trace' },
    });
  });

  it('keeps accepted traces as fallback when recorded actions are absent', () => {
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

    const displaySteps = mapRpaConfigureDisplaySteps(session);

    expect(displaySteps).toHaveLength(1);
    expect(displaySteps[0]).toMatchObject({
      id: 'trace-fill',
      traceId: 'trace-fill',
    });
    expect(getLegacyRpaSteps(session)).toEqual(session.steps);
  });

  it('falls back to legacy steps when no recorded actions or traces are present', () => {
    const session = {
      steps: [
        { id: 'click-1', action: 'click', description: 'Click search' },
      ],
      traces: [],
      recorded_actions: [],
    };

    expect(mapRpaConfigureDisplaySteps(session)).toEqual(session.steps);
  });

  it('maps recording diagnostics back to legacy step indexes', () => {
    const session = {
      steps: [
        {
          id: 'step-bad',
          action: 'fill',
          description: 'Input "foo" into None',
          locator_candidates: [{ playwright_locator: 'page.locator(".mystery")', selected: true }],
          url: 'https://example.test/search',
        },
      ],
      recording_diagnostics: [
        {
          related_step_id: 'step-bad',
          related_action_kind: 'fill',
          failure_reason: 'canonical_target_missing',
          raw_candidates: [{ playwright_locator: 'page.locator(".mystery")', selected: true }],
          page_state: { url: 'https://example.test/search' },
        },
      ],
    };

    const diagnostics = getManualRecordingDiagnostics(session);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]).toMatchObject({
      stepId: 'step-bad',
      stepIndex: 0,
      action: 'fill',
      failureReason: 'canonical_target_missing',
      validation: { status: 'broken', details: 'canonical target missing' },
      configurable: true,
      url: 'https://example.test/search',
    });
    expect(hasManualRecordingDiagnostics(session)).toBe(true);
  });

  it('allows deleting AI timeline items only when they have stable trace ids', () => {
    expect(isRpaTimelineStepDeletable({ source: 'ai', traceId: 'trace-ai-project' })).toBe(true);
    expect(isRpaTimelineStepDeletable({ source: 'ai' })).toBe(false);
    expect(isRpaTimelineStepDeletable({ source: 'record', traceId: 'trace-step-search' })).toBe(true);
  });

  it('preserves frame path from recorded actions', () => {
    const session = {
      recorded_actions: [
        {
          step_id: 'step-iframe',
          action_kind: 'click',
          description: 'click link("Runoob Note")',
          target: { method: 'role', role: 'link', name: 'Runoob Note' },
          frame_path: ['iframe[title="result"]', 'iframe[src="https://www.runoob.com"]'],
          validation: { status: 'ok' },
        },
      ],
    };

    const displaySteps = mapRpaConfigureDisplaySteps(session);

    expect(displaySteps[0].frame_path).toEqual([
      'iframe[title="result"]',
      'iframe[src="https://www.runoob.com"]',
    ]);
  });

  it('prefers trace timeline projection over legacy session fields', () => {
    const session = getRpaSessionWithTimeline({
      session: {
        steps: [{ id: 'legacy-step', action: 'click', description: 'Legacy should not display' }],
        recorded_actions: [{ step_id: 'legacy-action', action_kind: 'click' }],
        timeline: [
          {
            id: 'trace-trace-submit',
            kind: 'trace',
            trace_id: 'trace-submit',
            source: 'manual',
            trace_type: 'manual_action',
            action: 'click',
            title: 'Click submit',
            summary: 'button Submit',
            locator: { method: 'role', role: 'button', name: 'Submit' },
            locator_candidates: [
              {
                kind: 'role',
                locator: { method: 'role', role: 'button', name: 'Submit' },
                selected: true,
              },
            ],
            validation: { status: 'ok', details: 'Strict match' },
            editable: true,
          },
          {
            id: 'diagnostic-diag-bad-fill',
            kind: 'diagnostic',
            diagnostic_id: 'diag-bad-fill',
            trace_id: 'trace-bad-fill',
            action: 'fill',
            title: 'Repair fill',
            summary: 'canonical_target_missing',
            locator_candidates: [
              {
                kind: 'css',
                locator: { method: 'css', value: '#email' },
                selected: false,
              },
            ],
            validation: { status: 'broken', details: 'canonical_target_missing' },
            editable: true,
          },
        ],
      },
    });

    expect(hasRpaTimelineProjection(session)).toBe(true);
    expect(mapRpaConfigureDisplaySteps(session)).toEqual([
      expect.objectContaining({
        id: 'trace-trace-submit',
        traceId: 'trace-submit',
        diagnosticId: undefined,
        action: 'click',
        description: 'Click submit',
        target: { method: 'role', role: 'button', name: 'Submit' },
        configurable: true,
      }),
      expect.objectContaining({
        id: 'diagnostic-diag-bad-fill',
        traceId: 'trace-bad-fill',
        diagnosticId: 'diag-bad-fill',
        action: 'fill',
        description: 'Repair fill',
        configurable: true,
      }),
    ]);

    expect(getManualRecordingDiagnostics(session)).toEqual([
      expect.objectContaining({
        id: 'diag-bad-fill',
        stepIndex: null,
        traceId: 'trace-bad-fill',
        diagnosticId: 'diag-bad-fill',
        action: 'fill',
        validation: { status: 'broken', details: 'canonical target missing' },
        configurable: true,
      }),
    ]);
  });
});
