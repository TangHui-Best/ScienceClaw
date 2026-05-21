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
  stepId?: string;
  traceId?: string;
  diagnosticId?: string;
}

export interface RpaRecordingDiagnosticItem {
  id: string;
  stepId: string;
  stepIndex: number | null;
  traceId?: string;
  diagnosticId?: string;
  action: string;
  description: string;
  failureReason: string;
  locator_candidates: any[];
  validation: {
    status: string;
    details: string;
  };
  url?: string;
  source: 'record';
  configurable: boolean;
}

export interface RpaTimelineProjectionItem {
  id?: string;
  kind: 'trace' | 'diagnostic';
  trace_id?: string | null;
  diagnostic_id?: string | null;
  source?: string;
  trace_type?: string | null;
  action: string;
  title: string;
  summary: string;
  url?: string;
  frame_path?: string[];
  locator?: any;
  locator_candidates?: any[];
  validation?: { status?: string; details?: string };
  value?: string;
  sensitive?: boolean;
  editable?: boolean;
  deletable?: boolean;
  raw_trace?: any;
  raw_diagnostic?: any;
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

export const isRpaTimelineStepDeletable = (step: Pick<RpaConfigureStep, 'source' | 'traceId'>): boolean => {
  if (step.source === 'ai') return !!step.traceId;
  return true;
};

const formatDiagnosticReason = (reason?: string) => {
  if (!reason) return 'Unresolved diagnostic';
  return reason.replace(/_/g, ' ');
};

const normalizeCandidates = (candidates: any[], fallbackKind: string) => (
  (Array.isArray(candidates) ? candidates : []).map((candidate: any, index: number) => ({
    kind: candidate?.kind || fallbackKind,
    score: candidate?.score,
    selected: candidate?.selected ?? index === 0,
    reason: candidate?.reason,
    strict_match_count: candidate?.strict_match_count,
    visible_match_count: candidate?.visible_match_count,
    locator: candidate?.locator || candidate,
    playwright_locator: candidate?.playwright_locator,
    selector: candidate?.selector,
  }))
);

export const hasRpaTimelineProjection = (session: any): boolean => (
  Array.isArray(session?.timeline)
);

const projectionDisplayId = (item: RpaTimelineProjectionItem, index: number) => {
  if (item.kind === 'diagnostic') {
    return item.diagnostic_id || item.trace_id || item.id || `diagnostic-${index}`;
  }
  return item.trace_id || item.diagnostic_id || item.id || `trace-${index}`;
};

export const mapRpaTimelineProjection = (session: any): RpaConfigureStep[] => {
  const timeline = Array.isArray(session?.timeline) ? session.timeline : [];
  return timeline.map((item: RpaTimelineProjectionItem, index: number) => ({
    id: projectionDisplayId(item, index),
    traceId: item.kind === 'diagnostic' ? undefined : item.trace_id || undefined,
    diagnosticId: item.diagnostic_id || undefined,
    action: item.action || 'trace',
    target: item.locator || null,
    frame_path: Array.isArray(item.frame_path) ? item.frame_path : [],
    locator_candidates: normalizeCandidates(item.locator_candidates || [], item.action || 'trace'),
    validation: item.validation || {
      status: item.kind === 'diagnostic' ? 'broken' : 'ok',
      details: item.trace_type || item.kind,
    },
    value: item.value,
    description: item.title || item.summary || item.action,
    label: item.summary || item.action,
    sensitive: !!item.sensitive,
    url: item.url || '',
    source: item.source === 'ai' ? 'ai' : 'record',
    configurable: !!item.editable,
  }));
};

export const mapRpaConfigureDisplaySteps = (session: any): RpaConfigureStep[] => {
  return hasRpaTimelineProjection(session) ? mapRpaTimelineProjection(session) : [];
};

export const getLegacyRpaSteps = (_session: any): RpaConfigureStep[] => (
  []
);

export const getManualRecordingDiagnostics = (session: any): RpaRecordingDiagnosticItem[] => {
  if (!hasRpaTimelineProjection(session)) return [];

  return (session.timeline as RpaTimelineProjectionItem[])
    .filter((item) => item.kind === 'diagnostic')
    .map((item, index) => {
      const action = item.action || 'diagnostic';
      const details = item.validation?.details || item.summary || item.trace_type || 'trace diagnostic';
      return {
        id: item.diagnostic_id || item.id || `diagnostic-${index}`,
        stepId: '',
        stepIndex: null,
        traceId: item.trace_id || undefined,
        diagnosticId: item.diagnostic_id || undefined,
        action,
        description: item.title || item.summary || `${action} requires repair`,
        failureReason: details,
        locator_candidates: normalizeCandidates(item.locator_candidates || [], action),
        validation: {
          status: item.validation?.status || 'broken',
          details: formatDiagnosticReason(details),
        },
        url: item.url || '',
        source: 'record',
        configurable: Boolean(item.trace_id && item.locator_candidates?.length),
      };
    });
};

export const hasManualRecordingDiagnostics = (session: any): boolean => (
  getManualRecordingDiagnostics(session).length > 0
);
