import { describe, expect, it } from 'vitest';
import {
  getLegacyRpaSteps,
  getManualRecordingDiagnostics,
  hasManualRecordingDiagnostics,
  isRpaTimelineStepDeletable,
  mapRpaConfigureDisplaySteps,
} from './rpaConfigureTimeline';

describe('rpaConfigureTimeline', () => {
  it('maps display steps only from timeline projection trace and diagnostic ids', () => {
    const session = {
      timeline: [
        {
          id: 'backend-trace-projection-id',
          kind: 'trace',
          trace_id: 'trace-click-search',
          source: 'manual',
          trace_type: 'manual_action',
          action: 'click',
          title: 'Click search',
          summary: 'button("Search")',
          url: 'https://example.test/search',
          locator: { method: 'role', role: 'button', name: 'Search' },
          locator_candidates: [
            {
              kind: 'role',
              selected: true,
              locator: { method: 'role', role: 'button', name: 'Search' },
            },
          ],
          validation: { status: 'ok', details: 'Manual action' },
        },
        {
          id: 'backend-diagnostic-projection-id',
          kind: 'diagnostic',
          diagnostic_id: 'diagnostic-missing-target',
          trace_id: 'trace-fill-name',
          source: 'manual',
          action: 'fill',
          title: 'Fill needs repair',
          summary: 'canonical_target_missing',
          url: 'https://example.test/form',
          locator_candidates: [
            {
              kind: 'css',
              selected: true,
              locator: { method: 'css', selector: '.name' },
            },
          ],
          validation: { status: 'broken', details: 'canonical target missing' },
        },
      ],
    };

    const displaySteps = mapRpaConfigureDisplaySteps(session);

    expect(displaySteps).toHaveLength(2);
    expect(displaySteps[0]).toMatchObject({
      id: 'trace-click-search',
      traceId: 'trace-click-search',
      action: 'click',
      description: 'Click search',
      label: 'button("Search")',
      source: 'record',
      url: 'https://example.test/search',
      validation: { status: 'ok', details: 'Manual action' },
    });
    expect(displaySteps[0].target).toEqual({ method: 'role', role: 'button', name: 'Search' });
    expect(displaySteps[1]).toMatchObject({
      id: 'diagnostic-missing-target',
      diagnosticId: 'diagnostic-missing-target',
      action: 'fill',
      description: 'Fill needs repair',
      label: 'canonical_target_missing',
      source: 'record',
      validation: { status: 'broken', details: 'canonical target missing' },
    });
    expect(displaySteps[1].traceId).toBeUndefined();
    expect(displaySteps[1]).not.toHaveProperty('stepIndex');
  });

  it('does not fall back to legacy sources when timeline projection is absent', () => {
    const session = {
      steps: [
        { id: 'legacy-step', action: 'click', description: 'DO_NOT_USE_LEGACY step' },
      ],
      traces: [
        { trace_id: 'trace-legacy', trace_type: 'manual_action', description: 'DO_NOT_USE_LEGACY trace' },
      ],
      recorded_actions: [
        { step_id: 'legacy-action', action_kind: 'click', description: 'DO_NOT_USE_LEGACY action' },
      ],
      recording_diagnostics: [
        { related_step_id: 'legacy-step', failure_reason: 'DO_NOT_USE_LEGACY diagnostic' },
      ],
    };

    expect(mapRpaConfigureDisplaySteps(session)).toEqual([]);
    expect(getLegacyRpaSteps(session)).toEqual([]);
    expect(getManualRecordingDiagnostics(session)).toEqual([]);
    expect(hasManualRecordingDiagnostics(session)).toBe(false);
  });

  it('ignores legacy poison pills when a valid timeline projection exists', () => {
    const session = {
      timeline: [
        {
          kind: 'trace',
          trace_id: 'trace-valid',
          action: 'navigate',
          title: 'Open project',
          summary: 'https://example.test/project',
          url: 'https://example.test/project',
        },
      ],
      steps: [
        { id: 'legacy-step', action: 'click', description: 'DO_NOT_USE_LEGACY step' },
      ],
      recorded_actions: [
        { step_id: 'legacy-action', action_kind: 'click', description: 'DO_NOT_USE_LEGACY action' },
      ],
      recording_diagnostics: [
        { related_step_id: 'legacy-step', failure_reason: 'DO_NOT_USE_LEGACY diagnostic' },
      ],
    };

    const displaySteps = mapRpaConfigureDisplaySteps(session);

    expect(displaySteps).toHaveLength(1);
    expect(displaySteps[0]).toMatchObject({
      id: 'trace-valid',
      traceId: 'trace-valid',
      action: 'navigate',
      description: 'Open project',
    });
    expect(JSON.stringify(displaySteps)).not.toContain('DO_NOT_USE_LEGACY');
  });

  it('maps configurable values and sensitivity only from timeline projection fields', () => {
    const session = {
      timeline: [
        {
          kind: 'trace',
          trace_id: 'trace-password',
          action: 'fill',
          title: 'Fill password',
          summary: 'Password',
          locator: { method: 'role', role: 'textbox', name: 'Password' },
          value: '{{credential}}',
          sensitive: true,
          raw_trace: {
            value: 'DO_NOT_USE_RAW_TRACE_VALUE',
            sensitive: false,
          },
        },
      ],
    };

    const [displayStep] = mapRpaConfigureDisplaySteps(session);

    expect(displayStep).toMatchObject({
      id: 'trace-password',
      traceId: 'trace-password',
      action: 'fill',
      value: '{{credential}}',
      sensitive: true,
    });
    expect(JSON.stringify(displayStep)).not.toContain('DO_NOT_USE_RAW_TRACE_VALUE');
  });

  it('maps diagnostics only from timeline projection diagnostic ids', () => {
    const session = {
      timeline: [
        {
          kind: 'diagnostic',
          diagnostic_id: 'diagnostic-unresolved-fill',
          trace_id: 'trace-fill',
          action: 'fill',
          title: 'Fill requires repair',
          summary: 'canonical_target_missing',
          locator_candidates: [
            { playwright_locator: 'page.locator(".name")', selected: true },
          ],
          validation: { status: 'broken', details: 'canonical target missing' },
          url: 'https://example.test/form',
        },
      ],
      recording_diagnostics: [
        {
          related_step_id: 'legacy-step',
          failure_reason: 'DO_NOT_USE_LEGACY diagnostic',
        },
      ],
    };

    const diagnostics = getManualRecordingDiagnostics(session);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]).toMatchObject({
      id: 'diagnostic-unresolved-fill',
      stepId: '',
      stepIndex: null,
      traceId: 'trace-fill',
      diagnosticId: 'diagnostic-unresolved-fill',
      action: 'fill',
      description: 'Fill requires repair',
      failureReason: 'canonical target missing',
      validation: { status: 'broken', details: 'canonical target missing' },
      configurable: true,
      url: 'https://example.test/form',
    });
    expect(JSON.stringify(diagnostics)).not.toContain('DO_NOT_USE_LEGACY');
    expect(hasManualRecordingDiagnostics(session)).toBe(true);
  });

  it('allows deleting AI timeline items only when they have stable trace ids', () => {
    expect(isRpaTimelineStepDeletable({ source: 'ai', traceId: 'trace-ai-project' })).toBe(true);
    expect(isRpaTimelineStepDeletable({ source: 'ai' })).toBe(false);
    expect(isRpaTimelineStepDeletable({ source: 'record', traceId: 'trace-step-search' })).toBe(true);
  });

  it('does not expose diagnostic projection rows as trace deletable identities', () => {
    const session = {
      timeline: [
        {
          kind: 'diagnostic',
          diagnostic_id: 'diagnostic-delete-me',
          trace_id: 'trace-related-but-not-primary',
          action: 'click',
          title: 'Click requires repair',
          summary: 'locator_missing',
        },
      ],
    };

    const [diagnosticStep] = mapRpaConfigureDisplaySteps(session);

    expect(diagnosticStep).toMatchObject({
      id: 'diagnostic-delete-me',
      diagnosticId: 'diagnostic-delete-me',
    });
    expect(diagnosticStep.traceId).toBeUndefined();
    expect(isRpaTimelineStepDeletable(diagnosticStep)).toBe(true);
  });
});
