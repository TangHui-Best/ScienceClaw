export interface RpaConfigureStep {
  id: string;
  action: string;
  target?: any;
  frame_path?: string[];
  locator_candidates?: any[];
  validation?: {
    status?: string;
    details?: string;
  };
  value?: string;
  description?: string;
  label?: string;
  sensitive?: boolean;
  url?: string;
  source?: string;
  configurable?: boolean;
}

const TRACE_LABELS: Record<string, string> = {
  ai_operation: 'AI Trace',
  data_capture: 'Data Capture',
  dataflow_fill: 'Dataflow Fill',
  navigation: 'Navigation',
  manual_action: 'Manual',
};

export const formatRpaTraceType = (traceType?: string) => {
  if (!traceType) return 'Trace';
  return TRACE_LABELS[traceType] || traceType;
};

const firstLocatorCandidate = (trace: any) => {
  const candidates = Array.isArray(trace?.locator_candidates) ? trace.locator_candidates : [];
  if (candidates.length === 0) return null;
  const selected = candidates.find((candidate: any) => candidate?.selected) || candidates[0];
  return selected?.locator || selected || null;
};

const normalizeTraceCandidates = (trace: any) => {
  const candidates = Array.isArray(trace?.locator_candidates) ? trace.locator_candidates : [];
  return candidates.map((candidate: any, index: number) => ({
    kind: candidate?.kind || formatRpaTraceType(trace?.trace_type),
    score: candidate?.score,
    selected: candidate?.selected ?? index === 0,
    reason: candidate?.reason,
    strict_match_count: candidate?.strict_match_count,
    visible_match_count: candidate?.visible_match_count,
    locator: candidate?.locator || candidate,
  }));
};

const traceAction = (trace: any) => {
  if (trace?.trace_type === 'navigation') return 'navigate';
  if (trace?.trace_type === 'manual_action') return trace?.action || 'manual_action';
  return trace?.trace_type || trace?.action || 'trace';
};

export const mapRpaConfigureDisplaySteps = (session: any): RpaConfigureStep[] => {
  const traces = Array.isArray(session?.traces) ? session.traces : [];
  if (traces.length === 0) {
    return getLegacyRpaSteps(session);
  }

  return traces.map((trace: any, index: number) => {
    const traceTypeLabel = formatRpaTraceType(trace?.trace_type);
    const locator = firstLocatorCandidate(trace);
    const afterUrl = trace?.after_page?.url || '';
    return {
      id: String(trace?.trace_id || `trace-${index}`),
      action: traceAction(trace),
      target: locator,
      locator_candidates: normalizeTraceCandidates(trace),
      validation: {
        status: trace?.accepted === false ? 'warning' : 'ok',
        details: traceTypeLabel,
      },
      value: trace?.value,
      description: trace?.description || trace?.user_instruction || traceTypeLabel,
      label: trace?.user_instruction || trace?.action || traceTypeLabel,
      sensitive: false,
      url: afterUrl,
      source: trace?.source === 'ai' || trace?.trace_type === 'ai_operation' ? 'ai' : 'record',
      configurable: false,
    };
  });
};

export const getLegacyRpaSteps = (session: any): RpaConfigureStep[] => (
  Array.isArray(session?.steps) ? session.steps : []
);
