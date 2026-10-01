import type {
  AgentToolConfig,
  AgentToolSettings,
  AgentUpdate,
} from "@/api/client/types.gen";

type AgentTools = NonNullable<AgentUpdate["tools"]>;

export function delegatesOf(tools: AgentTools): AgentToolConfig[] {
  return tools.filter((t): t is AgentToolConfig => t.type === "agent");
}

// Every other tool is sent back untouched (settings drive approval rules on the
// backend); only the delegates are replaced.
export function withDelegates(
  tools: AgentTools,
  delegates: AgentToolConfig[]
): AgentTools {
  return [...tools.filter((t) => t.type !== "agent"), ...delegates];
}

// Mirrors the runtime's tool naming, so two delegates cannot become one tool.
export function delegateToolName(name: string): string {
  let sanitized = name
    .replace(/[^a-zA-Z0-9_]/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!sanitized || /^[0-9]/.test(sanitized)) sanitized = `agent_${sanitized}`;
  return `delegate_to_${sanitized}`;
}

const AGENT_CARD_PATH = "/.well-known/agent-card.json";

// Mirrors the backend: an agent is stored by its address, the URL its card is
// discovered under, whether its origin or its card URL was pasted.
export function agentAddress(url: string): string {
  let address = url.trim();
  if (address.endsWith(AGENT_CARD_PATH)) {
    address = address.slice(0, -AGENT_CARD_PATH.length);
  }
  return address.replace(/\/+$/, "");
}

// Any URL, empty included, marks the delegate remote: clearing the field to
// retype it must not turn it into a local one.
export function isRemoteDelegate(delegate: AgentToolConfig): boolean {
  return delegate.settings?.a2a_url != null;
}

type DelegatePatch = Partial<
  Pick<
    AgentToolSettings,
    "description_override" | "a2a_url" | "auth_secret_name"
  >
>;

export function patchDelegate(
  delegate: AgentToolConfig,
  patch: DelegatePatch
): AgentToolConfig {
  const cleaned = Object.fromEntries(
    Object.entries(patch).map(([key, value]) => [
      key,
      key === "a2a_url" || value?.trim() ? value : null,
    ])
  );
  return { ...delegate, settings: { ...delegate.settings, ...cleaned } };
}

export type RemoteDelegateProblem = "nameRequired" | "nameTaken" | "urlInvalid";

export function remoteDelegateProblem(
  draft: { name: string; url: string },
  tools: AgentTools
): RemoteDelegateProblem | null {
  const name = draft.name.trim();
  if (!name) return "nameRequired";
  const toolName = delegateToolName(name);
  if (delegatesOf(tools).some((d) => delegateToolName(d.name) === toolName)) {
    return "nameTaken";
  }
  let url: URL;
  try {
    url = new URL(draft.url.trim());
  } catch {
    return "urlInvalid";
  }
  if (!["http:", "https:"].includes(url.protocol) || !url.hostname) {
    return "urlInvalid";
  }
  return null;
}
