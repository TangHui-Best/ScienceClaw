import { apiClient } from './client';

export type RpaAgentSessionState = 'recording' | 'stopped' | 'configured' | 'compiled' | 'tested' | 'saved';

export interface BrowserRuntimeScope {
  page_runtime_ref: string;
  frame_runtime_ref: string;
}

export interface StartRpaAgentSessionResponse {
  session_id: string;
  state: 'recording';
  main_scope: BrowserRuntimeScope;
}

export interface CreationProjectionRow {
  row_id: string;
  candidate_id: string;
  ordinal: number;
  status: 'pending' | 'accepted' | 'rejected' | 'deleted' | 'effect';
  is_action: boolean;
  title: string;
  action_kind?: string | null;
  effect_kind?: string | null;
  trace_id?: string | null;
  sequence?: number | null;
  parent_trace_id?: string | null;
  diagnostic_code?: string | null;
  diagnostic_message?: string | null;
}

export interface RpaAgentProjectionResponse {
  state: RpaAgentSessionState;
  steps: CreationProjectionRow[];
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
  creation_steps: CreationProjectionRow[];
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
}

export interface TestRunPayload {
  inputs: Record<string, unknown>;
  secrets: Record<string, string>;
  data_assets: Record<string, string>;
}

export interface RpaAgentInstructionContext {
  business_terms: string[];
  required_variable_refs: string[];
  allowed_inputs: Record<string, string>;
  allowed_secret_names: string[];
  allowed_data_assets: Record<string, string>;
  page_aliases: Record<string, string>;
}

export interface RpaAgentManualInputPayload {
  input_id: string;
  kind: 'click' | 'text' | 'paste';
  x?: number;
  y?: number;
  text?: string;
}

export interface RpaAgentManualInputResponse {
  input_id: string;
  candidate_id: string;
  candidate_ids: string[];
}

// Real browser-use rounds can span up to 40 LLM/tool steps and may need to
// recover from provider retries or a rate-limited site. Keep the UI request
// alive for the backend-controlled execution window instead of reporting a
// false failure while the backend continues and settles the round.
export const RPA_AGENT_INSTRUCTION_TIMEOUT_MS = 600_000;

const sessionPath = (sessionId: string) => `/rpa-agent/sessions/${encodeURIComponent(sessionId)}`;

export async function startRpaAgentSession(browserSessionRef: string): Promise<StartRpaAgentSessionResponse> {
  const response = await apiClient.post('/rpa-agent/sessions', { browser_session_ref: browserSessionRef });
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
  modelId?: string,
): Promise<Record<string, unknown>> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/agent-instructions`, {
    instruction,
    ...context,
    ...(modelId ? { model_id: modelId } : {}),
  }, { timeout: RPA_AGENT_INSTRUCTION_TIMEOUT_MS });
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

export async function discardRpaAgentSession(sessionId: string): Promise<{ state: 'discarded' }> {
  const response = await apiClient.delete(sessionPath(sessionId));
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

export async function testRpaAgentSkill(sessionId: string, payload: TestRunPayload): Promise<Record<string, unknown>> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/test-run`, payload);
  return response.data;
}

export async function saveRpaAgentSkill(sessionId: string): Promise<Record<string, unknown>> {
  const response = await apiClient.post(`${sessionPath(sessionId)}/save`);
  return response.data;
}
