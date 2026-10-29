import { describe, expect, it } from "vitest";
import type { Part } from "@/lib/events/contract";
import { chatMcpApp } from "./chat";

function toolResult(data: Record<string, unknown>): Part {
  return {
    partId: "call-1",
    kind: "tool",
    eventType: "tool.result",
    data: {
      tool_name: "mcp__charts__show_chart",
      tool_call_id: "call-1",
      success: true,
      server_instance_id: "inst-1",
      mcp_app_tool: "show_chart",
      ...data,
    },
  };
}

describe("chatMcpApp", () => {
  it("replays the agent's call: arguments, text and structured content", () => {
    const app = chatMcpApp(
      toolResult({
        arguments: { region: "eu" },
        result: "3 rows",
        structured_content: { rows: [1, 2, 3] },
      })
    );

    expect(app).toEqual({
      instanceId: "inst-1",
      toolName: "show_chart",
      arguments: { region: "eu" },
      result: {
        content: [{ type: "text", text: "3 rows" }],
        structuredContent: { rows: [1, 2, 3] },
      },
    });
  });

  it("carries a non-text result as JSON and leaves out non-object structured content", () => {
    const app = chatMcpApp(
      toolResult({ result: { ok: true }, structured_content: [1, 2] })
    );

    expect(app?.result).toEqual({
      content: [{ type: "text", text: '{"ok":true}' }],
    });
    expect(app?.arguments).toEqual({});
  });

  it("opens nothing for a call that names no app, failed, or is still running", () => {
    expect(chatMcpApp(toolResult({ mcp_app_tool: undefined }))).toBeNull();
    expect(chatMcpApp(toolResult({ server_instance_id: "" }))).toBeNull();
    expect(chatMcpApp(toolResult({ success: false }))).toBeNull();
    expect(
      chatMcpApp({ ...toolResult({}), eventType: "tool.call" })
    ).toBeNull();
  });
});
