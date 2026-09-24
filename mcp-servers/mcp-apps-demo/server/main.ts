import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler } from "@modelcontextprotocol/server";
import cors from "cors";
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

// Stateless for both protocol eras: 2026-07-28 requests and 2025 clients each
// get a fresh server over the shared binding, and no session is ever minted.
const mcp = toNodeHandler(
  createMcpHandler(() => createServer(dataset, viewHtmlPath), {
    legacy: "stateless",
    onerror: (error) => console.error("MCP request failed:", error),
  })
);
// express.json() in createMcpExpressApp has already read the body.
app.all("/mcp", (req, res) => mcp(req, res, req.body));

app.listen(port, "127.0.0.1", (error) => {
  if (error) {
    console.error("Failed to start MCP server:", error);
    process.exit(1);
  }
  console.log(`Leads MCP App listening on http://localhost:${port}/mcp`);
  console.log(`Bound dataset: ${dataset.filePath}`);
});
