import type { McpWorkspaceToolPolicies } from "@/api/client/types.gen";

/** What the workspace does with one MCP tool whatever the agent's own settings say. */
export interface WorkspaceToolVerdict {
  effective: "approval" | "deny";
  reason: string | null;
}

/** Connection id → tool name → verdict; tools the workspace allows are absent. */
export type WorkspaceToolVerdicts = Record<
  string,
  Record<string, WorkspaceToolVerdict>
>;

/** The workspace's verdicts the agent editor shows beside each attached server's tools. */
export function workspaceToolVerdicts(
  policies: McpWorkspaceToolPolicies
): WorkspaceToolVerdicts {
  const verdicts: WorkspaceToolVerdicts = {};
  for (const instance of policies.instances) {
    const tools: Record<string, WorkspaceToolVerdict> = {};
    for (const tool of instance.tools) {
      if (tool.effective === "allow") continue;
      tools[tool.name] = {
        effective: tool.effective,
        reason: tool.reason ?? null,
      };
    }
    if (Object.keys(tools).length) verdicts[instance.instance_id] = tools;
  }
  return verdicts;
}
