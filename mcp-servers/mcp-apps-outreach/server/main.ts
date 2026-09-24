import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import cors from "cors";
import type { Request, Response } from "express";
import fs from "node:fs/promises";
import path from "node:path";
import { createServer, VIEW_FILES } from "./server.ts";
import { OutreachStore } from "./store.ts";

const dataPath = process.env.DATA_PATH;
if (!dataPath) {
  throw new Error("DATA_PATH is required: the dataset is bound at start, never bundled with the app");
}
const port = Number.parseInt(process.env.MCP_PORT ?? "3402", 10);
// Loopback by default. A container sets 0.0.0.0, where callers reach it by a
// service name, so the Host header is not a localhost name.
const host = process.env.MCP_HOST ?? "127.0.0.1";
const allowedHosts = process.env.MCP_ALLOWED_HOSTS?.split(",").map((h) => h.trim()).filter(Boolean);

// Bundled, this file is dist/server.js; from source it is server/main.ts.
const distDir = path.basename(import.meta.dirname) === "dist" ? import.meta.dirname : path.join(import.meta.dirname, "..", "dist");
const appDir = path.join(distDir, "app");
for (const file of VIEW_FILES) {
  await fs.access(path.join(appDir, file)).catch(() => {
    throw new Error(`${path.join(appDir, file)} is missing; run \`bun run build\` first`);
  });
}

const store = await OutreachStore.open(dataPath);

// Host header validation follows the bind address: on for loopback, off for
// 0.0.0.0 unless MCP_ALLOWED_HOSTS narrows it.
const app = createMcpExpressApp({ host, allowedHosts });
app.use(cors());

// Stateless Streamable HTTP: a fresh server per request, sharing one store.
app.all("/mcp", async (req: Request, res: Response) => {
  const server = createServer(store, appDir);
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

app.listen(port, host, (error) => {
  if (error) {
    console.error("Failed to start MCP server:", error);
    process.exit(1);
  }
  console.log(`Outreach MCP App listening on http://${host}:${port}/mcp`);
  console.log(`Bound dataset: ${store.filePath}`);
});
