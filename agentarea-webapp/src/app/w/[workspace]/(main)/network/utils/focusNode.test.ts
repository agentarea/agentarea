import { describe, expect, it } from "vitest";
import type { NetworkNodeData } from "../types";
import { findFocusedNode } from "./focusNode";

const node = (
  id: string,
  type: NetworkNodeData["type"],
  label: string
): NetworkNodeData => ({ id, type, label, metadata: {} });

const nodes = [
  node("11111111-1111-4111-8111-111111111111", "agent", "Triage"),
  node("22222222-2222-4222-8222-222222222222", "trigger", "Inbound Telegram"),
  node("11111111-1111-4111-8111-111111111111", "skill", "Shares an id"),
];

describe("resolving where a hand-off wants the graph opened", () => {
  it("finds the node a trigger panel pointed at", () => {
    expect(
      findFocusedNode(nodes, "agent:11111111-1111-4111-8111-111111111111")
    ).toBe(nodes[0]);
  });

  it("keeps kinds apart when an id is reused across them", () => {
    expect(
      findFocusedNode(nodes, "skill:11111111-1111-4111-8111-111111111111")
    ).toBe(nodes[2]);
  });

  it("opens unfocused rather than guessing when the target is gone", () => {
    expect(
      findFocusedNode(nodes, "agent:99999999-9999-4999-8999-999999999999")
    ).toBeNull();
  });

  it("ignores a parameter that is not a kind and an id", () => {
    expect(findFocusedNode(nodes, "")).toBeNull();
    expect(findFocusedNode(nodes, null)).toBeNull();
    expect(findFocusedNode(nodes, "agent")).toBeNull();
    expect(findFocusedNode(nodes, "agent:")).toBeNull();
    expect(findFocusedNode(nodes, ":abc")).toBeNull();
  });

  it("keeps an id that itself contains a colon intact", () => {
    const withColon = [node("a:b", "mcp_instance", "Odd id")];
    expect(findFocusedNode(withColon, "mcp_instance:a:b")).toBe(withColon[0]);
  });
});
