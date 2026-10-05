import type {
  BundleAgent,
  BundleAutomation,
  BundleChannel,
  BundleMcp,
  BundlePolicy,
  ImportPreview,
  InstallRequest,
  PreviewIssue,
  SetupField,
} from "@/api/client/types.gen";
import { defaultModelId } from "@/lib/default-model";
import type { Policy } from "@/types/policies";

// ${setup.<key>} reference used by an agent's model or a connection binding.
const SETUP_REF = /^\$\{setup\.([a-zA-Z0-9_]+)\}$/;

export function setupRefKey(value: string | null | undefined): string | null {
  const m = (value ?? "").match(SETUP_REF);
  return m ? m[1] : null;
}

type ModelLike = {
  id: string;
  model_name?: string | null;
  is_active?: boolean | null;
  managed_by?: string | null;
  tags?: string[] | null;
};

/** The model an agent's bundle entry names: a literal, or its setup field's default. */
export function suggestedModel(
  agent: BundleAgent,
  setupDefaults: Record<string, unknown>
): string | null {
  const key = setupRefKey(agent.model);
  const value = key ? setupDefaults[key] : agent.model;
  return typeof value === "string" && value ? value : null;
}

/**
 * The workspace model each agent starts on.
 *
 * A bundle travels between workspaces, so the model it names is a suggestion:
 * it is kept only when it is a model of this workspace, and every other agent
 * starts on the platform default. `null` when the workspace has neither, which
 * leaves the picker empty rather than guessing.
 */
export function initialAgentModels(
  agents: BundleAgent[],
  setupDefaults: Record<string, unknown>,
  models: ModelLike[]
): Record<string, string | null> {
  const ids = new Set(models.map((m) => m.id));
  const fallback = defaultModelId(models.map(asDefaultable));
  return Object.fromEntries(
    agents.map((agent) => {
      const named = suggestedModel(agent, setupDefaults);
      return [agent.key, named && ids.has(named) ? named : fallback];
    })
  );
}

function asDefaultable(m: ModelLike) {
  return {
    id: m.id,
    model_name: m.model_name ?? "",
    is_active: m.is_active ?? false,
    managed_by: m.managed_by ?? null,
    tags: m.tags ?? [],
  };
}

/** Setup field keys an MCP or channel's bindings read. */
export function boundSetupKeys(
  bindings: Record<string, string> | null | undefined
): string[] {
  return Object.values(bindings ?? {})
    .map((ref) => setupRefKey(ref))
    .filter((k): k is string => Boolean(k));
}

/** Setup field keys that only feed an agent's model; the agent's picker owns them. */
export function modelSetupKeys(agents: BundleAgent[]): Set<string> {
  return new Set(
    agents.map((a) => setupRefKey(a.model)).filter((k): k is string => !!k)
  );
}

/**
 * Which section renders each setup field: the connection or channel that binds
 * it, else the bundle-wide list. Model fields are left out, the agents own them.
 */
export function setupFieldPlacement(
  setup: SetupField[],
  mcps: BundleMcp[],
  channels: BundleChannel[],
  agents: BundleAgent[]
): {
  byOwner: Record<string, SetupField[]>;
  unbound: SetupField[];
} {
  const owner = new Map<string, string>();
  for (const item of [...mcps, ...channels]) {
    for (const key of boundSetupKeys(item.bindings)) {
      if (!owner.has(key)) owner.set(key, item.key);
    }
  }
  const modelKeys = modelSetupKeys(agents);
  const byOwner: Record<string, SetupField[]> = {};
  const unbound: SetupField[] = [];
  for (const field of setup) {
    if (modelKeys.has(field.key)) continue;
    const ownerKey = owner.get(field.key);
    if (ownerKey) (byOwner[ownerKey] ??= []).push(field);
    else unbound.push(field);
  }
  return { byOwner, unbound };
}

// ── Edit state ──────────────────────────────────────────────────────────────

export type BundleEdit = {
  setupValues: Record<string, unknown>;
  agentModels: Record<string, string | null>;
  agentOff: Set<string>;
  mcpOff: Set<string>;
  agentMcpOff: Record<string, Set<string>>;
  channelEnabled: Record<string, boolean>;
  autoEnabled: Record<string, boolean>;
  policyOff: Set<string>;
  policyEnabled: Record<string, boolean>;
};

export function initialEdit(
  preview: ImportPreview,
  models: ModelLike[]
): BundleEdit {
  const bundle = preview.bundle;
  const setupValues: Record<string, unknown> = {};
  for (const f of preview.setup ?? []) {
    if (f.default !== undefined && f.default !== null)
      setupValues[f.key] = f.default;
  }
  return {
    setupValues,
    agentModels: initialAgentModels(bundle.agents ?? [], setupValues, models),
    agentOff: new Set(),
    mcpOff: new Set(),
    agentMcpOff: {},
    channelEnabled: Object.fromEntries(
      (bundle.channels ?? []).map((c) => [c.key, Boolean(c.enabled)])
    ),
    autoEnabled: Object.fromEntries(
      (bundle.automations ?? []).map((a) => [a.key, Boolean(a.enabled)])
    ),
    policyOff: new Set(),
    policyEnabled: Object.fromEntries(
      (bundle.policies ?? []).map((p) => [p.key, p.enabled !== false])
    ),
  };
}

export type BundleEditAction =
  | { type: "reset"; edit: BundleEdit }
  | { type: "setSetup"; key: string; value: unknown }
  | { type: "setAgentModel"; key: string; modelId: string }
  | { type: "toggleAgent"; key: string; on: boolean }
  | { type: "toggleGlobalMcp"; key: string; on: boolean }
  | { type: "toggleAgentMcp"; agentKey: string; mcpKey: string; on: boolean }
  | { type: "toggleChannel"; key: string; on: boolean }
  | { type: "toggleAuto"; key: string; on: boolean }
  | { type: "togglePolicyInclude"; key: string; on: boolean }
  | { type: "togglePolicyEnabled"; key: string; on: boolean };

// Add/remove a key from a Set immutably (`present` = should it be in the set).
function withKey(set: Set<string>, key: string, present: boolean): Set<string> {
  const next = new Set(set);
  if (present) next.add(key);
  else next.delete(key);
  return next;
}

export function bundleEditReducer(
  state: BundleEdit,
  action: BundleEditAction
): BundleEdit {
  switch (action.type) {
    case "reset":
      return action.edit;
    case "setSetup":
      return {
        ...state,
        setupValues: { ...state.setupValues, [action.key]: action.value },
      };
    case "setAgentModel":
      return {
        ...state,
        agentModels: { ...state.agentModels, [action.key]: action.modelId },
      };
    // `on` = included → the key is ABSENT from the "off" set.
    case "toggleAgent":
      return {
        ...state,
        agentOff: withKey(state.agentOff, action.key, !action.on),
      };
    case "toggleGlobalMcp":
      return {
        ...state,
        mcpOff: withKey(state.mcpOff, action.key, !action.on),
      };
    case "toggleAgentMcp":
      return {
        ...state,
        agentMcpOff: {
          ...state.agentMcpOff,
          [action.agentKey]: withKey(
            state.agentMcpOff[action.agentKey] ?? new Set(),
            action.mcpKey,
            !action.on
          ),
        },
      };
    case "toggleChannel":
      return {
        ...state,
        channelEnabled: { ...state.channelEnabled, [action.key]: action.on },
      };
    case "toggleAuto":
      return {
        ...state,
        autoEnabled: { ...state.autoEnabled, [action.key]: action.on },
      };
    case "togglePolicyInclude":
      return {
        ...state,
        policyOff: withKey(state.policyOff, action.key, !action.on),
      };
    case "togglePolicyEnabled":
      return {
        ...state,
        policyEnabled: { ...state.policyEnabled, [action.key]: action.on },
      };
  }
}

export function isAgentMcpOn(
  edit: BundleEdit,
  agentKey: string,
  mcpKey: string
): boolean {
  return (
    !edit.mcpOff.has(mcpKey) &&
    !(edit.agentMcpOff[agentKey]?.has(mcpKey) ?? false)
  );
}

/** Connections that end up installed: kept, and attached to a kept agent. */
export function installedMcpKeys(
  agents: BundleAgent[],
  edit: BundleEdit
): Set<string> {
  const used = new Set<string>();
  for (const a of agents) {
    if (edit.agentOff.has(a.key)) continue;
    for (const ref of a.mcps ?? [])
      if (isAgentMcpOn(edit, a.key, ref)) used.add(ref);
  }
  return used;
}

/** Required setup fields still empty; mirrors the backend's required_setup_errors. */
export function missingRequiredSetup(
  preview: ImportPreview,
  edit: BundleEdit
): SetupField[] {
  const modelKeys = modelSetupKeys(preview.bundle.agents ?? []);
  return (preview.setup ?? []).filter((f) => {
    if (!f.required || modelKeys.has(f.key)) return false;
    const v = edit.setupValues[f.key];
    return v === undefined || v === null || v === "";
  });
}

/** Kept agents that still have no model to run on. */
export function agentsWithoutModel(
  preview: ImportPreview,
  edit: BundleEdit
): BundleAgent[] {
  return (preview.bundle.agents ?? []).filter(
    (a) => !edit.agentOff.has(a.key) && !edit.agentModels[a.key]
  );
}

/**
 * Analyzer findings that still apply. The analyzer reads the bundle as shipped,
 * where an agent may name no model; the install sends the model picked here,
 * so that finding is settled by the picker, not by the bundle.
 */
export function openIssues(
  preview: ImportPreview,
  edit: BundleEdit
): PreviewIssue[] {
  return (preview.issues ?? []).filter(
    (issue) =>
      !(
        issue.entity_key &&
        edit.agentModels[issue.entity_key] &&
        / has no model$/.test(issue.message)
      )
  );
}

/** The bundle and setup values to send to /install, with every choice applied. */
export function buildInstallRequest(
  preview: ImportPreview,
  edit: BundleEdit,
  canAdminister: boolean
): InstallRequest {
  const bundle = preview.bundle;
  const agents: BundleAgent[] = (bundle.agents ?? [])
    .filter((a) => !edit.agentOff.has(a.key))
    .map((a) => ({
      ...a,
      model: edit.agentModels[a.key] ?? a.model,
      mcps: (a.mcps ?? []).filter((ref) => isAgentMcpOn(edit, a.key, ref)),
    }));
  const keptAgents = new Set(agents.map((a) => a.key));
  const installed = installedMcpKeys(bundle.agents ?? [], edit);
  const channels: BundleChannel[] = (bundle.channels ?? [])
    .filter((c) => keptAgents.has(c.agent))
    .map((c) => ({ ...c, enabled: edit.channelEnabled[c.key] ?? false }));
  const automations: BundleAutomation[] = (bundle.automations ?? [])
    .filter((a) => keptAgents.has(a.agent))
    .map((a) => ({ ...a, enabled: edit.autoEnabled[a.key] ?? false }));
  const policies: BundlePolicy[] = canAdminister
    ? (bundle.policies ?? [])
        .filter((p) => !edit.policyOff.has(p.key))
        .map((p) => ({ ...p, enabled: edit.policyEnabled[p.key] !== false }))
    : [];

  // A model setup field no agent reads any more is still a declared field; give
  // it the model its first agent was given so a required one does not refuse.
  const setupValues = { ...edit.setupValues };
  for (const a of bundle.agents ?? []) {
    const key = setupRefKey(a.model);
    const picked = edit.agentModels[a.key];
    if (key && picked && setupValues[key] == null) setupValues[key] = picked;
  }

  return {
    bundle: {
      ...bundle,
      agents,
      mcps: (bundle.mcps ?? []).filter((m) => installed.has(m.key)),
      channels,
      automations,
      policies,
    },
    setup_values: setupValues,
  };
}

/**
 * A bundle policy in the shape the policies page describes. Its subject is an
 * agent key or the workspace, not yet an id.
 */
export function bundlePolicyAsPolicy(
  policy: BundlePolicy,
  enabled: boolean
): Policy {
  const subject = policy.subject ?? "workspace";
  return {
    id: policy.key,
    enabled,
    priority: policy.priority ?? 0,
    subject_type: subject === "workspace" ? "workspace" : "agent",
    subject_id: subject,
    target: policy.target,
    effect: policy.effect,
    params: policy.params ?? {},
    condition: policy.condition ?? null,
  };
}
