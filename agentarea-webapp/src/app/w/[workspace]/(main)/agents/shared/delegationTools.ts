import type { AgentUpdate } from "@/api/client/types.gen";

type AgentTools = NonNullable<AgentUpdate["tools"]>;

export function delegatesOf(tools: AgentTools): string[] {
  return tools.filter((t) => t.type === "agent").map((t) => t.name);
}

// Existing tools are sent back untouched (settings drive approval rules on the
// backend); only delegates the user toggled are added or removed.
export function withDelegates(
  tools: AgentTools,
  delegates: ReadonlySet<string>
): AgentTools {
  const kept = tools.filter((t) => t.type !== "agent" || delegates.has(t.name));
  const present = new Set(delegatesOf(tools));
  const added = [...delegates]
    .filter((name) => !present.has(name))
    .map((name) => ({ type: "agent" as const, name }));
  return [...kept, ...added];
}
