import { apiClient } from './client';

export type RpaAgentSessionState = 'recording' | 'stopped' | 'configured' | 'compiled' | 'tested' | 'saved';

export interface StartRpaAgentSessionResponse {
  session_id: string;
  state: 'recording';
  browser_session_ref: string;
  page_ref: string;
  generation: string;
}

export type CaptureStatus = 'capturing' | 'observing' | 'captured' | 'incomplete';
export type ExecutionStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type ReplayStatus = 'pending' | 'deterministic_ready' | 'insufficient_evidence' | 'needs_confirmation';
export type CompileMode = null | 'playwright' | 'agent' | 'needs_confirmation';

export interface TimelineObservation {
  trace_id: string;
  action: string;
  summary: string;
}

export interface RecordingTimelineItem {
  id: string;
  kind: 'manual' | 'ai_instruction';
  ordinal: number;
  title: string;
  capture_status: CaptureStatus;
  execution_status: ExecutionStatus;
  replay_status: ReplayStatus;
  compile_mode: CompileMode;
  observations: TimelineObservation[];
}

export interface RpaAgentProjectionResponse {
  session_id: string;
  recording_state: RpaAgentSessionState;
  items: RecordingTimelineItem[];
}

export interface BindingLocation {
  trace_id: string;
  binding_name: string;
  direction: 'input' | 'output';
  kind: string;
  ref?: string | null;
  sensitive: boolean;
}

export interface StopRpaAgentSessionResponse {
  state: 'stopped';
  configuration_draft: import('@/utils/rpaAgentSkillConfiguration').SkillConfigurationDraft;
  configuration_options: {
    binding_locations: BindingLocation[];
    readiness: { ready: boolean; issues: Array<Record<string, unknown>> };
  };
}

export interface CompiledRpaAgentSkill {
  state: 'compiled';
  artifact_files: string[];
  artifact_hash: string;
  source_hash: string;
}

export interface TestRunPayload {
  inputs: Record<string, unknown>;
  secrets: Record<string, string>;
  data_assets: Record<string, string>;
}

export interface RpaAgentInstructionContext {
  model_id?: string;
  business_terms: string[];
  required_variable_refs: string[];
  allowed_inputs: Record<string, string>;
  allowed_secret_names: string[];
  allowed_data_assets: Record<string, string>;
  page_aliases: Record<string, string>;
}

export interface RpaAgentManualInputPayload {
  input_id: string;
  kind: 'click' | 'text' | 'paste' | 'navigate';
  x?: number;
  y?: number;
  text?: string;
}

export interface RpaAgentManualInputResponse {
  input_id: string;
  draft_id: string;
  capture_status: 'capturing' | 'captured' | 'incomplete';
}

export interface RpaAgentInstructionAccepted {
  step_id: string;
  ordinal: number;
  execution_status: ExecutionStatus;
}

const sessionPath = (sessionId: string) => `/rpa-agent/sessions/${encodeURIComponent(sessionId)}`;

export async function startRpaAgentSession(startUrl?: string): Promise<StartRpaAgentSessionResponse> {
  const response = await apiClient.post('/rpa-agent/sessions', startUrl ? { start_url: startUrl } : {});
  return response.data;
}

export async function rerecordRpaAgentSession(
  sessionId: string,
  startUrl?: string,
): Promise<StartRpaAgentSessionResponse> {
  const response = await apiClient.post(
    `${sessionPath(sessionId)}/rerecord`,
    startUrl ? { start_url: startUrl } : {},
  );
  return response.data;
}

export async function reserveRpaAgentManualAction(sessionId: string, payload: {
  candidate_id: string;
  page_runtime_ref: string;
  frame_runtime_ref: string;
}): Promise<{ reservation_token: string }> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/manual-reservations`, payload);
  return response.data;
}

export async function recordRpaAgentManualEvent(sessionId: string, payload: Record<string, unknown>): Promise<{ candidate_ids: string[] }> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/manual-events`, payload);
  return response.data;
}

export async function dispatchRpaAgentManualInput(
  sessionId: string,
  payload: RpaAgentManualInputPayload,
): Promise<RpaAgentManualInputResponse> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/manual-inputs`, payload);
  return response.data;
}

export async function runRpaAgentInstruction(
  sessionId: string,
  instruction: string,
  context: RpaAgentInstructionContext = {
    business_terms: [], required_variable_refs: [], allowed_inputs: {},
    allowed_secret_names: [], allowed_data_assets: {}, page_aliases: {},
  },
  idempotencyKey: string = crypto.randomUUID(),
): Promise<RpaAgentInstructionAccepted> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/agent-instructions`, {
    instruction,
    ...context,
  }, { headers: { 'Idempotency-Key': idempotencyKey } });
  return response.data;
}

export async function getRpaAgentProjection(sessionId: string): Promise<RpaAgentProjectionResponse> {
  const response = await apiClient.get(`${sessionPath(sessionId)}/projection`);
  return response.data;
}

export async function stopRpaAgentSession(sessionId: string): Promise<StopRpaAgentSessionResponse> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/stop`);
  return response.data;
}

export async function configureRpaAgentSkill(
  sessionId: string,
  draft: import('@/utils/rpaAgentSkillConfiguration').SkillConfigurationDraft,
): Promise<Record<string, unknown>> {
  const response = await apiClient.put(`${sessionPath(sessionId)}/configuration`, draft);
  return response.data;
}

export async function compileRpaAgentSkill(sessionId: string): Promise<CompiledRpaAgentSkill> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/compile`);
  return response.data;
}

export const RPA_AGENT_TEST_RUN_TIMEOUT_MS = 10 * 60 * 1000;

export async function testRpaAgentSkill(sessionId: string, payload: TestRunPayload): Promise<Record<string, unknown>> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/test-run`, payload, {
    timeout: RPA_AGENT_TEST_RUN_TIMEOUT_MS,
  });
  return response.data;
}

export async function saveRpaAgentSkill(sessionId: string): Promise<Record<string, unknown>> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/save`);
  return response.data;
}
