import { describe, expect, it } from "vitest";
import { toToolsPayload } from "./agentContract";

describe("toToolsPayload", () => {
  it("keeps null (all tools) distinct from an empty selection (no tools)", () => {
    const tools = toToolsPayload({
      mcp_server_configs: [
        { mcp_server_id: "github-all", allowed_tools: null },
        { mcp_server_id: "github-none", allowed_tools: [] },
        {
          mcp_server_id: "github-some",
          allowed_tools: [{ tool_name: "list_issues" }],
        },
      ],
      openapi_configs: [
        { openapi_connection_id: "crm-all", allowed_tools: null },
        { openapi_connection_id: "crm-none", allowed_tools: [] },
      ],
    });

    expect(tools).toMatchObject([
      { type: "mcp", settings: { allowed_tools: null } },
      { type: "mcp", settings: { allowed_tools: [] } },
      {
        type: "mcp",
        settings: {
          allowed_tools: [
            { tool_name: "list_issues", requires_user_confirmation: false },
          ],
        },
      },
      { type: "openapi", settings: { allowed_tools: null } },
      { type: "openapi", settings: { allowed_tools: [] } },
    ]);
  });
});
