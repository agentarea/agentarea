import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import {
  McpServer,
  type CallToolResult,
  type ReadResourceResult,
} from "@modelcontextprotocol/server";
import fs from "node:fs/promises";
import { z } from "zod";
import { LEAD_STATUSES } from "../shared/leads.ts";
import type { CsvDataset, DatasetSnapshot } from "./dataset.ts";

const VIEW_URI = "ui://leads/view.html";

const snapshotSchema = z.object({
  dataset: z.string(),
  columns: z.array(z.string()),
  rows: z.array(z.record(z.string(), z.string())),
});

function snapshotResult(snapshot: DatasetSnapshot): CallToolResult {
  return {
    content: [
      { type: "text", text: `${snapshot.rows.length} leads from ${snapshot.dataset}` },
    ],
    structuredContent: snapshot,
  };
}

/**
 * The app is the view resource plus its tools. The data is not part of it:
 * `dataset` is supplied by whoever runs the server.
 */
export function createServer(dataset: CsvDataset, viewHtmlPath: string): McpServer {
  const server = new McpServer({ name: "Leads MCP App", version: "0.1.0" });

  registerAppTool(
    server,
    "show_leads",
    {
      title: "Show leads",
      description: "Open the leads table for the dataset bound to this app.",
      inputSchema: z.object({}),
      outputSchema: snapshotSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: VIEW_URI } },
    },
    async () => snapshotResult(await dataset.read()),
  );

  // Visible to the view only: a button press in the UI runs it directly,
  // without a model turn in between.
  registerAppTool(
    server,
    "set_lead_status",
    {
      title: "Set lead status",
      description: "Change one lead's status in the bound dataset.",
      inputSchema: z.object({ id: z.string(), status: z.enum(LEAD_STATUSES) }),
      outputSchema: snapshotSchema,
      annotations: { readOnlyHint: false },
      _meta: { ui: { resourceUri: VIEW_URI, visibility: ["app"] } },
    },
    async ({ id, status }) => snapshotResult(await dataset.updateCell(id, "status", status)),
  );

  registerAppResource(
    server,
    "Leads view",
    VIEW_URI,
    { mimeType: RESOURCE_MIME_TYPE, description: "Interactive table for a leads dataset" },
    async (): Promise<ReadResourceResult> => ({
      contents: [
        {
          uri: VIEW_URI,
          mimeType: RESOURCE_MIME_TYPE,
          text: await fs.readFile(viewHtmlPath, "utf-8"),
        },
      ],
    }),
  );

  return server;
}
