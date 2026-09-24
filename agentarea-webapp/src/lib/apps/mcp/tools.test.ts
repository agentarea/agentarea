import { RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/app-bridge";
import { describe, expect, it } from "vitest";
import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import {
  mcpAppEntries,
  mcpAppLinkArguments,
  resolveMcpAppTool,
  uiResourceFromReadResult,
} from "./tools";

const schema = { type: "object", properties: {} };

function instance(
  tools: Array<Record<string, unknown>>,
  overrides: Partial<McpServerInstanceResponse> = {}
): McpServerInstanceResponse {
  return {
    id: "3f0f4a52-6f5e-4c5b-9f1f-4b8f9f2b1c11",
    name: "Charts",
    description: null,
    server_spec_id: "spec",
    json_spec: { type: "command" },
    verification: { status: "succeeded" },
    created_at: "2026-09-24T00:00:00Z",
    updated_at: "2026-09-24T00:00:00Z",
    tools,
    ...overrides,
  };
}

const entryTool = {
  name: "show-chart",
  title: "Show chart",
  description: "Opens the chart",
  inputSchema: schema,
  _meta: { ui: { resourceUri: "ui://charts/app.html" } },
};
const appOnlyTool = {
  name: "refresh-chart",
  inputSchema: schema,
  _meta: {
    ui: { resourceUri: "ui://charts/app.html", visibility: ["app"] },
  },
};
const modelOnlyTool = {
  name: "summarize",
  inputSchema: schema,
  _meta: { ui: { visibility: ["model"] } },
};
const plainTool = { name: "ping", inputSchema: schema };
// Malformed or empty visibility admits nobody, as the agent-side filter does.
const stringVisibilityTool = {
  name: "string-visibility",
  inputSchema: schema,
  _meta: { ui: { resourceUri: "ui://charts/app.html", visibility: "model" } },
};
const noAudienceTool = {
  name: "no-audience",
  inputSchema: schema,
  _meta: { ui: { resourceUri: "ui://charts/app.html", visibility: [] } },
};

describe("mcpAppEntries", () => {
  it("lists model-visible tools with a UI resource and nothing else", () => {
    const entries = mcpAppEntries([
      instance([
        entryTool,
        appOnlyTool,
        modelOnlyTool,
        plainTool,
        stringVisibilityTool,
        noAudienceTool,
        {
          name: "broken",
          inputSchema: schema,
          _meta: { ui: { resourceUri: "https://x/app" } },
        },
      ]),
    ]);

    expect(entries).toEqual([
      {
        instanceId: "3f0f4a52-6f5e-4c5b-9f1f-4b8f9f2b1c11",
        instanceName: "Charts",
        toolName: "show-chart",
        title: "Show chart",
        description: "Opens the chart",
        resourceUri: "ui://charts/app.html",
        requiresInput: false,
      },
    ]);
  });

  it("skips bundles and connections that are not verified", () => {
    expect(
      mcpAppEntries([
        instance([entryTool], { json_spec: { type: "bundle" } }),
        instance([entryTool], { verification: { status: "failed" } }),
      ])
    ).toEqual([]);
  });

  it("marks an entry that needs arguments the host cannot supply", () => {
    const [entry] = mcpAppEntries([
      instance([
        {
          ...entryTool,
          inputSchema: { ...schema, required: ["region"] },
        },
      ]),
    ]);
    expect(entry.requiresInput).toBe(true);
  });
});

describe("resolveMcpAppTool", () => {
  const charts = instance([
    entryTool,
    appOnlyTool,
    modelOnlyTool,
    plainTool,
    stringVisibilityTool,
    noAudienceTool,
  ]);

  it("lets an app call its own tools and ordinary tools", () => {
    expect(resolveMcpAppTool(charts, "refresh-chart", "app").name).toBe(
      "refresh-chart"
    );
    expect(resolveMcpAppTool(charts, "ping", "app").name).toBe("ping");
  });

  it("keeps model-only tools and tools with unreadable visibility away from the app", () => {
    for (const name of ["summarize", "string-visibility", "no-audience"]) {
      expect(() => resolveMcpAppTool(charts, name, "app")).toThrow(
        /not callable from an MCP App/
      );
    }
  });

  it("lets the host start only an entry tool", () => {
    expect(resolveMcpAppTool(charts, "show-chart", "host").name).toBe(
      "show-chart"
    );
    expect(() => resolveMcpAppTool(charts, "refresh-chart", "host")).toThrow(
      /not an MCP App entry point/
    );
    expect(() => resolveMcpAppTool(charts, "ping", "host")).toThrow(
      /not an MCP App entry point/
    );
  });

  it("rejects unknown tools, bundles and unverified connections", () => {
    expect(() => resolveMcpAppTool(charts, "missing", "app")).toThrow(
      /not exposed/
    );
    expect(() =>
      resolveMcpAppTool(
        instance([entryTool], { json_spec: { type: "bundle" } }),
        "show-chart",
        "host"
      )
    ).toThrow(/bundle/);
    expect(() =>
      resolveMcpAppTool(
        instance([entryTool], { verification: { status: "failed" } }),
        "show-chart",
        "host"
      )
    ).toThrow(/not been verified/);
  });
  it("lets an app link open only entry tools the app could call itself", () => {
    const modelOnlyEntry = {
      name: "show-private",
      inputSchema: schema,
      _meta: {
        ui: { resourceUri: "ui://charts/private.html", visibility: ["model"] },
      },
    };
    const linked = instance([
      entryTool,
      appOnlyTool,
      plainTool,
      modelOnlyEntry,
    ]);

    expect(resolveMcpAppTool(linked, "show-chart", "link").name).toBe(
      "show-chart"
    );
    expect(() => resolveMcpAppTool(linked, "show-private", "link")).toThrow(
      /not callable from an MCP App/
    );
    expect(() => resolveMcpAppTool(linked, "refresh-chart", "link")).toThrow(
      /not an MCP App entry point/
    );
    expect(() => resolveMcpAppTool(linked, "ping", "link")).toThrow(
      /not an MCP App entry point/
    );
  });
});

describe("mcpAppLinkArguments", () => {
  const lead = {
    name: "show-lead",
    inputSchema: {
      type: "object" as const,
      properties: {
        contact_id: { type: "string" },
        days: { type: "integer" },
        score: { type: "number" },
        handled: { type: "boolean" },
      },
    },
  };

  it("converts query values to the types the input schema declares", () => {
    expect(
      mcpAppLinkArguments(lead, {
        contact_id: "007",
        days: "30",
        score: "0.5",
        handled: "false",
        extra: "kept",
      })
    ).toEqual({
      contact_id: "007",
      days: 30,
      score: 0.5,
      handled: false,
      extra: "kept",
    });
  });

  it("refuses values that do not convert", () => {
    expect(() => mcpAppLinkArguments(lead, { days: "3.5" })).toThrow(
      /"days" must be an integer/
    );
    expect(() => mcpAppLinkArguments(lead, { score: "" })).toThrow(
      /"score" must be a number/
    );
    expect(() => mcpAppLinkArguments(lead, { handled: "yes" })).toThrow(
      /"handled" must be true or false/
    );
  });
});

describe("uiResourceFromReadResult", () => {
  const uri = "ui://charts/app.html";

  it("decodes a base64 blob and reads the UI metadata", () => {
    const resource = uiResourceFromReadResult(
      {
        contents: [
          {
            uri,
            mimeType: RESOURCE_MIME_TYPE,
            blob: Buffer.from("<p>é</p>").toString("base64"),
            _meta: {
              ui: {
                csp: { connectDomains: ["https://api.example"] },
                prefersBorder: false,
              },
            },
          },
        ],
      },
      uri
    );

    expect(resource).toEqual({
      uri,
      html: "<p>é</p>",
      csp: { connectDomains: ["https://api.example"] },
      permissions: undefined,
      prefersBorder: false,
    });
  });

  it("rejects content that is not an MCP App document", () => {
    expect(() =>
      uiResourceFromReadResult(
        { contents: [{ uri, mimeType: "text/html", text: "<p></p>" }] },
        uri
      )
    ).toThrow(/MIME type/);
    expect(() =>
      uiResourceFromReadResult(
        {
          contents: [
            { uri, mimeType: RESOURCE_MIME_TYPE, text: "<p></p>" },
            { uri, mimeType: RESOURCE_MIME_TYPE, text: "<p></p>" },
          ],
        },
        uri
      )
    ).toThrow(/exactly one/);
  });

  it("fails loudly on malformed UI metadata", () => {
    expect(() =>
      uiResourceFromReadResult(
        {
          contents: [
            {
              uri,
              mimeType: RESOURCE_MIME_TYPE,
              text: "<p></p>",
              _meta: { ui: { csp: { connectDomains: "https://api.example" } } },
            },
          ],
        },
        uri
      )
    ).toThrow(/metadata is invalid/);
  });
});
