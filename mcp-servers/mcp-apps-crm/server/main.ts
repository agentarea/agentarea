import { CallerContextError, callerFromHeaders, contextOptionsFromEnv, verifyContextToken } from "@kit/context/caller.ts";
import { EventDispatcher } from "@kit/events/subscriptions.ts";
import { openAppStore } from "@kit/store/store.ts";
import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler } from "@modelcontextprotocol/server";
import cors from "cors";
import fs from "node:fs/promises";
import path from "node:path";
import { DB_FILE, MIGRATIONS, seedDemo } from "./db.ts";
import { EVENT_TYPES } from "./events.ts";
import { createServer, VIEW_FILES } from "./server.ts";
import { CrmStore } from "./store.ts";

const port = Number.parseInt(process.env.MCP_PORT ?? "3411", 10);
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

// Set by the platform for an instance whose spec opts into caller context: then
// every change is made as the person or agent the platform names, and only so.
const contextOptions = contextOptionsFromEnv();

// The CRM lives in the instance's MCP storage (MCP_MANAGER_URL, MCP_INSTANCE_ID, MCP_STORAGE_TOKEN), never on local disk.
const store = await openAppStore({ file: DB_FILE, migrations: MIGRATIONS, seed: seedDemo });
if (!(await store.read(CrmStore.loadIfSetUp))) {
  console.log("The CRM is empty: until setup_crm writes it, the server offers only that tool.");
}
// Posts CRM events to webhook subscribers: right after each change, and failed POSTs again on a timer.
const dispatcher = new EventDispatcher({ app: store, types: EVENT_TYPES });
dispatcher.start();
dispatcher.kick();

// Host header validation follows the bind address: on for loopback, off for
// 0.0.0.0 unless MCP_ALLOWED_HOSTS narrows it.
const app = createMcpExpressApp({ host, allowedHosts });
app.use(cors());

// Stateless for both protocol eras: 2026-07-28 requests and 2025 clients each
// get a fresh server over the shared store, and no session is ever minted.
const mcp = toNodeHandler(
  createMcpHandler(
    async ({ requestInfo }) => {
      // The platform signs who each request is for; a context that does not verify fails the request.
      const caller = contextOptions && requestInfo ? await callerFromHeaders(requestInfo.headers, contextOptions) : null;
      return createServer(store, appDir, await store.read(CrmStore.loadIfSetUp), {
        caller,
        required: contextOptions !== null,
      }, dispatcher);
    },
    {
      legacy: "stateless",
      onerror: (error) => console.error("MCP request failed:", error),
    },
  ),
);
// A request whose caller context does not verify is refused before it reaches
// the MCP server, as the context contract answers a bad token.
if (contextOptions) {
  app.use("/mcp", async (req, res, next) => {
    const token = req.header("x-agentarea-context");
    if (token === undefined) return next();
    try {
      await verifyContextToken(token, contextOptions);
      next();
    } catch (error) {
      if (!(error instanceof CallerContextError)) return next(error);
      res.status(401).json({ jsonrpc: "2.0", id: req.body?.id ?? null, error: { code: -32001, message: error.message } });
    }
  });
}
// express.json() in createMcpExpressApp has already read the body.
app.all("/mcp", (req, res) => mcp(req, res, req.body));

app.listen(port, host, (error) => {
  if (error) {
    console.error("Failed to start MCP server:", error);
    process.exit(1);
  }
  console.log(`Sales CRM MCP App listening on http://${host}:${port}/mcp`);
  console.log(`App storage: ${store.file}, schema version ${store.schemaVersion}`);
});
