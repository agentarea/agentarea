import { z } from "zod";
import type {
  McpInstanceToolPolicy,
  PolicyRuleResponse,
} from "@/api/client/types.gen";
import { connectionToolName, toolTarget } from "@/types/policies";

/**
 * A connection tool's workspace default. "allow" is the absence of a rule: the
 * engine allows what no rule restricts, and an allow rule would instead turn
 * the workspace into an allowlist that shuts every other tool out.
 */
export type ToolPolicy = "allow" | "approval" | "deny";

export const TOOL_POLICIES: readonly ToolPolicy[] = [
  "allow",
  "approval",
  "deny",
];

type ToolPolicyRule = Pick<
  PolicyRuleResponse,
  | "id"
  | "enabled"
  | "subject_type"
  | "subject_id"
  | "target"
  | "effect"
  | "condition"
  | "params"
>;

// The engine matches rule names as fnmatch patterns; a tool whose name holds
// one of these must not become a pattern that names its siblings too.
const escapeGlob = (name: string) =>
  name.replace(/[[*?]/g, (char) => `[${char}]`);

/** The rule target naming one tool of one connection, as the runtime checks it. */
export function toolPolicyTarget(instanceId: string, toolName: string): string {
  return toolTarget(connectionToolName(instanceId, escapeGlob(toolName)));
}

/**
 * A rule this screen owns: the workspace's plain deny or approval. An approval
 * that names its approvers was written in Govern and stays there: switching
 * the tool here never deletes it.
 */
function isDefaultRule(rule: ToolPolicyRule, workspaceId: string): boolean {
  const approvers = (rule.params as { approvers?: unknown } | undefined)
    ?.approvers;
  return (
    rule.enabled &&
    rule.subject_type === "workspace" &&
    rule.subject_id === workspaceId &&
    !rule.condition &&
    (rule.effect === "deny" ||
      (rule.effect === "approval" &&
        !(Array.isArray(approvers) && approvers.length)))
  );
}

/** A tool's default set here, and what the workspace's engine decides for it. */
export type ToolPolicyState = Pick<
  McpInstanceToolPolicy,
  "default" | "effective" | "reason"
>;

const STRICTNESS: Record<ToolPolicy, number> = {
  allow: 0,
  approval: 1,
  deny: 2,
};

/**
 * The state after the default moves to `policy`, before the server answers:
 * what other rules impose (the verdict, when it was stricter than the old
 * default) still holds over the new default.
 */
export function withDefault(
  state: ToolPolicyState,
  policy: ToolPolicy
): ToolPolicyState {
  const fromOthers =
    STRICTNESS[state.effective] > STRICTNESS[state.default]
      ? state.effective
      : "allow";
  const stricter = STRICTNESS[fromOthers] > STRICTNESS[policy];
  return {
    default: policy,
    effective: stricter ? fromOthers : policy,
    reason: stricter ? state.reason : null,
  };
}

/**
 * What it takes to move a tool to `policy`: the rule to create, if no rule of
 * that effect exists yet, and the other default rules to delete.
 */
export function planToolPolicyChange(
  rules: readonly ToolPolicyRule[],
  workspaceId: string,
  target: string,
  policy: ToolPolicy
): { create: "deny" | "approval" | null; remove: string[] } {
  const current = rules.filter(
    (rule) => rule.target === target && isDefaultRule(rule, workspaceId)
  );
  const keep = current.some((rule) => rule.effect === policy);
  return {
    create: policy === "allow" || keep ? null : policy,
    remove: current
      .filter((rule) => rule.effect !== policy)
      .map((rule) => rule.id),
  };
}

/** The default every one of `toolNames` has, or `null` when they differ. */
export function sharedToolPolicy(
  states: Readonly<Record<string, ToolPolicyState>>,
  toolNames: readonly string[]
): ToolPolicy | null {
  const found = new Set(
    toolNames.map((name) => states[name]?.default ?? "allow")
  );
  return found.size === 1 ? [...found][0] : null;
}

// What a server action is asked to change: anything else is refused before a
// rule is read, so a crafted call cannot target another connection by pattern.
const toolPolicyChange = z.object({
  instanceId: z.string().uuid(),
  toolNames: z.array(z.string().min(1)).min(1).max(1000),
  policy: z.enum(["allow", "approval", "deny"]),
});

export type ToolPolicyChange = z.infer<typeof toolPolicyChange>;

/** The change a server action was asked for, or `null` when it is not one. */
export function parseToolPolicyChange(input: unknown): ToolPolicyChange | null {
  const parsed = toolPolicyChange.safeParse(input);
  return parsed.success ? parsed.data : null;
}
