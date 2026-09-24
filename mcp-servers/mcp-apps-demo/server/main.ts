import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import cors from "cors";
import type { Request, Response } from "express";
import fs from "node:fs/promises";
import path from "node:path";
import { LEAD_COLUMNS } from "../shared/leads.ts";
import { CsvDataset } from "./dataset.ts";
import { createServer } from "./server.ts";

const datasetPath = process.env.DATASET_PATH;
if (!datasetPath) {
  throw new Error("DATASET_PATH is required: the dataset is bound at start, never bundled with the app");
}
const port = Number.parseInt(process.env.MCP_PORT ?? "3401", 10);
const viewHtmlPath = path.join(import.meta.dirname, "..", "dist", "app", "mcp-app.html");

await fs.access(viewHtmlPath).catch(() => {
  throw new Error(`${viewHtmlPath} is missing; run \`bun run build\` first`);
});
const dataset = new CsvDataset(path.resolve(datasetPath), LEAD_COLUMNS);
// Refuse to start on a dataset the view cannot render.
await dataset.read();

const app = createMcpExpressApp();
app.use(cors());

// Stateless Streamable HTTP: a fresh server per request, sharing one binding.
app.all("/mcp", async (req: Request, res: Response) => {
  const server = createServer(dataset, viewHtmlPath);
  const transport = new NodeStreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  res.on("close", () => {
    transport.close().catch(() => {});
    server.close().catch(() => {});
  });

  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (error) {
    console.error("MCP request failed:", error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: { code: -32603, message: "Internal server error" },
        id: null,
      });
    }
  }
});

app.listen(port, "127.0.0.1", (error) => {
  if (error) {
    console.error("Failed to start MCP server:", error);
    process.exit(1);
  }
  console.log(`Leads MCP App listening on http://localhost:${port}/mcp`);
  console.log(`Bound dataset: ${dataset.filePath}`);
});
