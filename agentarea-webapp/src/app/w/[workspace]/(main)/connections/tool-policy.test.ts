import { describe, expect, it } from "vitest";
import {
  planToolPolicyChange,
  sharedToolPolicy,
  toolPolicyTarget,
  withDefault,
} from "./tool-policy";

const WS = "ws-1";
const INSTANCE = "inst-1";

const rule = (
  id: string,
  target: string,
  effect: "deny" | "approval" | "allow",
  overrides: Partial<{
    enabled: boolean;
    subject_type: "workspace" | "agent";
    subject_id: string;
    condition: string | null;
  }> = {}
) => ({
  id,
  target,
  effect,
  enabled: true,
  subject_type: "workspace" as const,
  subject_id: WS,
  condition: null,
  params: {},
  ...overrides,
});

describe("withDefault", () => {
  it("keeps what another rule imposes over a looser new default", () => {
    const state = {
      default: "allow" as const,
      effective: "deny" as const,
      reason: "glob",
    };
    expect(withDefault(state, "approval")).toEqual({
      default: "approval",
      effective: "deny",
      reason: "glob",
    });
  });

  it("lets the new default rule when nothing else is stricter", () => {
    const state = {
      default: "deny" as const,
      effective: "deny" as const,
      reason: null,
    };
    expect(withDefault(state, "allow")).toEqual({
      default: "allow",
      effective: "allow",
      reason: null,
    });
  });
});

describe("toolPolicyTarget", () => {
  it("escapes glob characters so a name never matches its siblings", () => {
    expect(toolPolicyTarget(INSTANCE, "a*b?[c]")).toBe(
      `tool:mcp:${INSTANCE}:a[*]b[?][[]c]`
    );
  });
});

describe("planToolPolicyChange", () => {
  const target = toolPolicyTarget(INSTANCE, "send");

  it("creates the new rule and removes the one it replaces", () => {
    const rules = [rule("1", target, "approval")];
    expect(planToolPolicyChange(rules, WS, target, "deny")).toEqual({
      create: "deny",
      remove: ["1"],
    });
  });

  it("allow removes every default rule and creates none", () => {
    const rules = [rule("1", target, "approval"), rule("2", target, "deny")];
    expect(planToolPolicyChange(rules, WS, target, "allow")).toEqual({
      create: null,
      remove: ["1", "2"],
    });
  });

  it("keeps an approval that names its approvers", () => {
    const rules = [
      { ...rule("1", target, "approval"), params: { approvers: ["user:u1"] } },
    ];
    expect(planToolPolicyChange(rules, WS, target, "allow")).toEqual({
      create: null,
      remove: [],
    });
  });

  it("leaves rules it does not own alone", () => {
    const rules = [
      rule("1", target, "deny"),
      rule("2", target, "approval", { subject_type: "agent", subject_id: "a" }),
    ];
    expect(planToolPolicyChange(rules, WS, target, "deny")).toEqual({
      create: null,
      remove: [],
    });
  });
});

describe("sharedToolPolicy", () => {
  it("names the default every tool shares, a tool without one counting as allow", () => {
    const deny = {
      default: "deny" as const,
      effective: "deny" as const,
      reason: null,
    };
    expect(sharedToolPolicy({ a: deny, b: deny }, ["a", "b"])).toBe("deny");
    expect(sharedToolPolicy({}, ["a", "b"])).toBe("allow");
    expect(sharedToolPolicy({ a: deny }, ["a", "b"])).toBeNull();
  });
});
