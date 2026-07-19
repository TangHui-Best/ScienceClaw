export type DraftInput = {
  ref: string;
  title: string;
  required: boolean;
  value_type: 'string' | 'number' | 'boolean';
  default?: string | number | boolean;
};

export interface SkillConfigurationDraft {
  schema_version: 'skill-configuration-draft/v0.1';
  skill: { name: string; description: string };
  inputs: DraftInput[];
  secrets: Array<{ ref: string; title: string; required: boolean }>;
  asset_inputs: Array<{ ref: string; title: string; required: boolean }>;
  outputs: Array<{ name: string; title: string; variable_ref: string; value_type: 'string' | 'number' | 'boolean' | 'json' }>;
  asset_outputs: Array<{ name: string; title: string; asset_ref: string }>;
  binding_promotions: BindingPromotion[];
  manual_fallbacks?: Record<string, {
    trace_id: string;
    instruction: string;
    scope_hint: { page_ref: string; url?: string | null; title?: string | null; frame_path: unknown[] };
  }>;
  agent_steps?: Record<string, {
    step_id: string;
    output_refs: string[];
    expected_effects: Array<Record<string, unknown>>;
    allowed_input_refs: string[];
    allowed_secret_refs: string[];
    allowed_asset_refs: string[];
    page_aliases: Record<string, { page_ref: string; url: string; title: string }>;
    business_terms: string[];
    model_policy: { mode: 'runtime_default' | 'configured_model'; model_ref?: string | null };
    timeout_seconds: number;
  }>;
  stage_2_rules?: string;
}

export interface BindingPromotion {
  trace_id: string;
  binding_name: string;
  to_kind: 'skill_input' | 'secret';
  ref: string;
}

export interface CreationRouteSnapshot {
  sessionId: string;
  browserSessionRef: string;
  configurationDraft?: SkillConfigurationDraft;
  bindingLocations?: Array<Record<string, unknown>>;
  recordingSteps?: Array<{
    id: string;
    ordinal: number;
    kind: 'manual' | 'ai_instruction';
    title: string;
    replayStatus: 'pending' | 'deterministic_ready' | 'insufficient_evidence' | 'needs_confirmation';
    compileMode: null | 'playwright' | 'agent' | 'needs_confirmation';
  }>;
  artifactHash?: string;
  artifactFiles?: string[];
  configurationState?: 'configured' | 'compiled';
  testPassed?: boolean;
  savedRef?: string;
}

const storageKey = (sessionId: string) => `rpa-agent:${sessionId}`;

export function applyBindingPromotion(draft: SkillConfigurationDraft, promotion: BindingPromotion): SkillConfigurationDraft {
  const promotions = draft.binding_promotions.filter(
    (item) => item.trace_id !== promotion.trace_id || item.binding_name !== promotion.binding_name,
  );
  return { ...draft, binding_promotions: [...promotions, { ...promotion }] };
}

type BindingLocationKey = { trace_id: string; binding_name: string };

const identifierPart = (value: string) => {
  const normalized = value.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^[^A-Za-z]+/, '').replace(/[.-]+/g, '_');
  return normalized || 'binding';
};

export function generatedBindingRef(location: BindingLocationKey, toKind: BindingPromotion['to_kind']): string {
  const name = identifierPart(location.binding_name).slice(0, 48);
  const trace = identifierPart(location.trace_id).slice(-24);
  return `${name}_${trace}_${toKind === 'secret' ? 'secret' : 'input'}`;
}

export function promoteBindingLocation(
  draft: SkillConfigurationDraft,
  location: BindingLocationKey,
  toKind: BindingPromotion['to_kind'],
): SkillConfigurationDraft {
  const previous = draft.binding_promotions.find(
    (item) => item.trace_id === location.trace_id && item.binding_name === location.binding_name,
  );
  const ref = generatedBindingRef(location, toKind);
  const remainingPromotions = draft.binding_promotions.filter(
    (item) => item.trace_id !== location.trace_id || item.binding_name !== location.binding_name,
  );
  let inputs = draft.inputs.map((item) => ({ ...item }));
  let secrets = draft.secrets.map((item) => ({ ...item }));

  if (previous && !remainingPromotions.some((item) => item.ref === previous.ref)) {
    if (previous.to_kind === 'skill_input') inputs = inputs.filter((item) => item.ref !== previous.ref);
    else secrets = secrets.filter((item) => item.ref !== previous.ref);
  }

  if (toKind === 'skill_input' && !inputs.some((item) => item.ref === ref)) {
    inputs.push({ ref, title: location.binding_name, required: true, value_type: 'string' });
  }
  if (toKind === 'secret' && !secrets.some((item) => item.ref === ref)) {
    secrets.push({ ref, title: location.binding_name, required: true });
  }
  return {
    ...draft,
    inputs,
    secrets,
    binding_promotions: [...remainingPromotions, {
      trace_id: location.trace_id,
      binding_name: location.binding_name,
      to_kind: toKind,
      ref,
    }],
  };
}

export function renamePromotedBindingRef(
  draft: SkillConfigurationDraft,
  kind: BindingPromotion['to_kind'],
  oldRef: string,
  requestedRef: string,
): SkillConfigurationDraft {
  const newRef = requestedRef.trim();
  if (!newRef) throw new Error('configuration.ref_required');
  if (newRef !== oldRef) {
    const declarationRefs = [...draft.inputs.map((item) => item.ref), ...draft.secrets.map((item) => item.ref)];
    const conflictsWithDeclaration = declarationRefs.some((ref) => ref === newRef);
    const conflictsWithPromotion = draft.binding_promotions.some((item) => item.ref === newRef && item.ref !== oldRef);
    if (conflictsWithDeclaration || conflictsWithPromotion) throw new Error('configuration.ref_duplicate');
  }

  return {
    ...draft,
    inputs: kind === 'skill_input'
      ? draft.inputs.map((item) => item.ref === oldRef ? { ...item, ref: newRef } : item)
      : draft.inputs.map((item) => ({ ...item })),
    secrets: kind === 'secret'
      ? draft.secrets.map((item) => item.ref === oldRef ? { ...item, ref: newRef } : item)
      : draft.secrets.map((item) => ({ ...item })),
    binding_promotions: draft.binding_promotions.map((item) => (
      item.to_kind === kind && item.ref === oldRef ? { ...item, ref: newRef } : { ...item }
    )),
  };
}

export function setDraftInputDefault(
  draft: SkillConfigurationDraft,
  inputRef: string,
  enabled: boolean,
  rawValue?: unknown,
): SkillConfigurationDraft {
  return {
    ...draft,
    inputs: draft.inputs.map((input) => {
      if (input.ref !== inputRef) return { ...input };
      const { default: _default, ...withoutDefault } = input;
      if (!enabled) return withoutDefault as DraftInput;
      if (input.value_type === 'number') {
        const value = Number(rawValue);
        if (!Number.isFinite(value)) throw new Error('configuration.number_default_invalid');
        return { ...withoutDefault, default: value } as DraftInput;
      }
      if (input.value_type === 'boolean') {
        const value = typeof rawValue === 'boolean' ? rawValue : rawValue === 'true';
        return { ...withoutDefault, default: value } as DraftInput;
      }
      return { ...withoutDefault, default: String(rawValue ?? '') } as DraftInput;
    }),
  };
}

export function saveCreationSnapshot(snapshot: CreationRouteSnapshot): void {
  const safe = scrubSecrets(snapshot) as CreationRouteSnapshot;
  sessionStorage.setItem(storageKey(snapshot.sessionId), JSON.stringify(safe));
}

function scrubSecrets(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(scrubSecrets);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .filter(([key]) => !/^(?:secret|password|token|credential)_?(?:values?|plaintext)$/i.test(key))
    .map(([key, item]) => [key, scrubSecrets(item)]));
}

export function loadCreationSnapshot(sessionId: string): CreationRouteSnapshot | null {
  const raw = sessionStorage.getItem(storageKey(sessionId));
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as CreationRouteSnapshot;
    if (value.sessionId !== sessionId) return null;
    return value;
  } catch {
    return null;
  }
}
