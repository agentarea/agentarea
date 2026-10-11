import { openAppStore } from "@kit/store/store.ts";
import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler } from "@modelcontextprotocol/server";
import cors from "cors";
import fs from "node:fs/promises";
import path from "node:path";
import { DB_FILE, MIGRATIONS, seedDemo } from "./db.ts";
import { createServer, VIEW_FILES } from "./server.ts";
import { BooksStore } from "./store.ts";

const port = Number.parseInt(process.env.MCP_PORT ?? "3412", 10);
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

// The books live in the instance's MCP storage (MCP_MANAGER_URL, MCP_INSTANCE_ID, MCP_STORAGE_TOKEN), never on local disk.
const store = await openAppStore({ file: DB_FILE, migrations: MIGRATIONS, seed: seedDemo });
await store.read(BooksStore.load).catch((error: Error) => {
  console.warn(`${error.message} Until it has data, every MCP request fails.`);
});

// Host header validation follows the bind address: on for loopback, off for
// 0.0.0.0 unless MCP_ALLOWED_HOSTS narrows it.
const app = createMcpExpressApp({ host, allowedHosts });
app.use(cors());

// Stateless for both protocol eras: 2026-07-28 requests and 2025 clients each
// get a fresh server over the shared store, and no session is ever minted.
const mcp = toNodeHandler(
  createMcpHandler(async () => createServer(store, appDir, await store.read(BooksStore.load)), {
    legacy: "stateless",
    onerror: (error) => console.error("MCP request failed:", error),
  })
);
// express.json() in createMcpExpressApp has already read the body.
app.all("/mcp", (req, res) => mcp(req, res, req.body));

app.listen(port, host, (error) => {
  if (error) {
    console.error("Failed to start MCP server:", error);
    process.exit(1);
  }
  console.log(`Books MCP App listening on http://${host}:${port}/mcp`);
  console.log(`App storage: ${store.file}, schema version ${store.schemaVersion}`);
});
