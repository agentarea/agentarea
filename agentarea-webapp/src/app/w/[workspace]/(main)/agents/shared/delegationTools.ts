import type { AgentResponse, AgentUpdate } from "@/api/client/types.gen";

// Existing tools are sent back untouched (settings drive approval rules on the
// backend); only delegates the user toggled are added or removed.
export function withDelegates(
  tools: NonNullable<AgentResponse["tools"]>,
  delegates: ReadonlySet<string>
): NonNullable<AgentUpdate["tools"]> {
  const kept = tools.filter((t) => t.type !== "agent" || delegates.has(t.name));
  const present = new Set(
    tools.filter((t) => t.type === "agent").map((t) => t.name)
  );
  const added = [...delegates]
    .filter((name) => !present.has(name))
    .map((name) => ({ type: "agent" as const, name }));
  return [...kept, ...added];
}
