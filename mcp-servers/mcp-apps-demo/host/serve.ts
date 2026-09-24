/**
 * Two HTTP servers on two ports, so the host page and the app sandbox are
 * different origins:
 * - host (8480): the test page and its config
 * - sandbox (8481): sandbox.html only, with CSP set as an HTTP header
 */
import type { McpUiResourceCsp } from "@modelcontextprotocol/ext-apps";
import express from "express";
import path from "node:path";

const HOST_PORT = Number.parseInt(process.env.HOST_PORT ?? "8480", 10);
const SANDBOX_PORT = Number.parseInt(process.env.SANDBOX_PORT ?? "8481", 10);
const MCP_URL = process.env.MCP_URL ?? "http://localhost:3401/mcp";
const DIST = path.join(import.meta.dirname, "..", "dist", "host");

const host = express();
host.get("/config.json", (_req, res) => {
  res.json({ mcpUrl: MCP_URL, sandboxUrl: `http://localhost:${SANDBOX_PORT}/sandbox.html` });
});
host.use((req, res, next) => {
  if (req.path === "/sandbox.html") {
    res.status(404).send("The sandbox is served from its own origin");
    return;
  }
  next();
});
host.use(express.static(DIST));

// Entries that could break out of a directive or inject a keyword are dropped.
function sanitize(domains?: string[]): string {
  return (domains ?? []).filter((d) => typeof d === "string" && !/[;\r\n'" ]/.test(d)).join(" ");
}

function cspHeader(csp?: McpUiResourceCsp): string {
  const resources = sanitize(csp?.resourceDomains);
  const connect = sanitize(csp?.connectDomains);
  const frames = sanitize(csp?.frameDomains);
  const baseUri = sanitize(csp?.baseUriDomains);
  return [
    "default-src 'self' 'unsafe-inline'",
    `script-src 'self' 'unsafe-inline' blob: data: ${resources}`.trim(),
    `style-src 'self' 'unsafe-inline' blob: data: ${resources}`.trim(),
    `img-src 'self' data: blob: ${resources}`.trim(),
    `font-src 'self' data: blob: ${resources}`.trim(),
    `connect-src 'self' ${connect}`.trim(),
    frames ? `frame-src ${frames}` : "frame-src 'none'",
    "object-src 'none'",
    baseUri ? `base-uri ${baseUri}` : "base-uri 'none'",
  ].join("; ");
}

const sandbox = express();
sandbox.get("/sandbox.html", (req, res) => {
  let csp: McpUiResourceCsp | undefined;
  if (typeof req.query.csp === "string") {
    try {
      csp = JSON.parse(req.query.csp);
    } catch {
      res.status(400).send("csp must be JSON");
      return;
    }
  }
  res.setHeader("Content-Security-Policy", cspHeader(csp));
  res.setHeader("Cache-Control", "no-store");
  res.sendFile(path.join(DIST, "sandbox.html"));
});
sandbox.use((_req, res) => {
  res.status(404).send("Only sandbox.html is served on this origin");
});

host.listen(HOST_PORT, "127.0.0.1", (error) => {
  if (error) throw error;
  console.log(`Test host:  http://localhost:${HOST_PORT}`);
});
sandbox.listen(SANDBOX_PORT, "127.0.0.1", (error) => {
  if (error) throw error;
  console.log(`Sandbox:    http://localhost:${SANDBOX_PORT}/sandbox.html`);
});
