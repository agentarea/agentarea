/**
 * A file-backed stand-in for the manager's MCP storage API, for local runs
 * and tests. Same routes (/mcp/{instance}/storage/...), bearer check, ETags and
 * preconditions as the real one: a PUT needs `If-Match` or `If-None-Match: *`
 * (428 without), a stale one gets 412, another instance's path gets 403.
 *
 *   bun dev-server.ts --dir .storage --port 3420 --instance dev --token dev [-- <command...>]
 *
 * With a command after `--`, it runs that command with MCP_MANAGER_URL,
 * MCP_INSTANCE_ID and MCP_STORAGE_TOKEN set and stops when the command exits.
 */
import fs from "node:fs";
import path from "node:path";
import { storageUrl } from "./client.ts";

const DEFAULT_MAX_BYTES = 64 * 1024 * 1024;

export type DevStorageOptions = {
  dir: string;
  instanceId: string;
  token: string;
  port?: number;
  hostname?: string;
  maxBytes?: number;
  /** Log every write and its outcome. */
  verbose?: boolean;
};

type Meta = { etag: string; size: number; contentType: string; lastModified: string };

export type DevStorage = {
  /** The instance's storage API, as storageUrl(managerUrl, instanceId) builds it. */
  url: string;
  managerUrl: string;
  instanceId: string;
  port: number;
  stop: () => void;
  stats: { puts: number; conflicts: number };
};

const text = (status: number, body: string) => new Response(body, { status, headers: { "Content-Type": "text/plain" } });

/** The object path from the URL, or an error message when it is not a valid relative path. */
function objectPath(encoded: string): string | { error: string } {
  let value: string;
  try {
    value = encoded.split("/").map(decodeURIComponent).join("/");
  } catch {
    return { error: "path is not valid UTF-8" };
  }
  if (value.split("/").some((s) => s === "" || s === "." || s === "..")) return { error: "path has an empty, . or .. segment" };
  if (Buffer.byteLength(value, "utf-8") > 512) return { error: "path is longer than 512 bytes" };
  return value;
}

export function startDevStorage(options: DevStorageOptions): DevStorage {
  const root = path.resolve(options.dir);
  const objects = path.join(root, "objects");
  const metas = path.join(root, "meta");
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;
  const stats = { puts: 0, conflicts: 0 };

  const metaFile = (p: string) => path.join(metas, `${p}.json`);
  const readMeta = (p: string): Meta | null => {
    try {
      return JSON.parse(fs.readFileSync(metaFile(p), "utf-8")) as Meta;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  };
  const writeAtomic = (file: string, data: Uint8Array | string) => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const temp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(temp, data);
    fs.renameSync(temp, file);
  };
  const headers = (meta: Meta) => ({ ETag: meta.etag, "Content-Type": meta.contentType, "Content-Length": String(meta.size) });

  function list(prefix: string): Response {
    const found: { path: string; size: number; etag: string; last_modified: string }[] = [];
    const walk = (dir: string) => {
      if (!fs.existsSync(dir)) return;
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith(".json")) {
          const p = path.relative(metas, full).slice(0, -".json".length).split(path.sep).join("/");
          if (!p.startsWith(prefix)) continue;
          const meta = readMeta(p)!;
          found.push({ path: p, size: meta.size, etag: meta.etag, last_modified: meta.lastModified });
        }
      }
    };
    walk(metas);
    found.sort((a, b) => a.path.localeCompare(b.path));
    return Response.json({ objects: found });
  }

  async function handle(request: Request): Promise<Response> {
    if (request.headers.get("Authorization") !== `Bearer ${options.token}`) return text(401, "missing or invalid bearer token");
    const url = new URL(request.url);
    const route = /^\/mcp\/([^/]+)\/storage(\/.*)?$/.exec(url.pathname);
    if (!route) return text(404, "not found");
    if (decodeURIComponent(route[1]) !== options.instanceId) return text(403, "the token does not grant this MCP instance");
    if (route[2] === "/objects" && request.method === "GET") return list(url.searchParams.get("prefix") ?? "");
    const basePath = `/mcp/${route[1]}/storage`;
    const prefix = `${basePath}/objects/`;
    if (!url.pathname.startsWith(prefix)) return text(404, "not found");
    const p = objectPath(url.pathname.slice(prefix.length));
    if (typeof p !== "string") return text(400, p.error);

    const ifMatch = request.headers.get("If-Match");
    const ifNoneMatch = request.headers.get("If-None-Match");
    switch (request.method) {
      case "HEAD":
      case "GET": {
        const meta = readMeta(p);
        if (!meta) return text(404, "no such object");
        const body = request.method === "GET" ? new Uint8Array(fs.readFileSync(path.join(objects, p))) : null;
        return new Response(body, { status: 200, headers: headers(meta) });
      }
      case "PUT": {
        if (ifMatch === null && ifNoneMatch === null) return text(428, "PUT needs If-Match or If-None-Match: *");
        if (ifMatch !== null && ifNoneMatch !== null) return text(400, "pass exactly one of If-Match and If-None-Match");
        if (ifNoneMatch !== null && ifNoneMatch !== "*") return text(400, "If-None-Match must be *");
        if (Number(request.headers.get("Content-Length") ?? 0) > maxBytes) return text(413, `body is over ${maxBytes} bytes`);
        const body = new Uint8Array(await request.arrayBuffer());
        if (body.byteLength > maxBytes) return text(413, `body is over ${maxBytes} bytes`);
        // From here to the write nothing awaits: the check and the write are one step.
        const current = readMeta(p);
        if ((ifNoneMatch === "*" && current) || (ifMatch !== null && current?.etag !== ifMatch)) {
          stats.conflicts += 1;
          if (options.verbose) console.log(`PUT ${p} 412 (${ifMatch ?? "If-None-Match: *"} is not ${current?.etag ?? "absent"})`);
          return text(412, "precondition failed");
        }
        const meta: Meta = {
          etag: `"${new Bun.CryptoHasher("md5").update(body).digest("hex")}"`,
          size: body.byteLength,
          contentType: request.headers.get("Content-Type") ?? "application/octet-stream",
          lastModified: new Date().toISOString(),
        };
        writeAtomic(path.join(objects, p), body);
        writeAtomic(metaFile(p), JSON.stringify(meta));
        stats.puts += 1;
        if (options.verbose) console.log(`PUT ${p} 200 ${meta.etag} ${meta.size} bytes`);
        return new Response(null, { status: 200, headers: { ETag: meta.etag } });
      }
      case "DELETE": {
        if (ifMatch === null) return text(428, "DELETE needs If-Match");
        const current = readMeta(p);
        if (!current) return text(404, "no such object");
        if (current.etag !== ifMatch) return text(412, "precondition failed");
        fs.rmSync(metaFile(p));
        fs.rmSync(path.join(objects, p));
        return new Response(null, { status: 204 });
      }
      default:
        return text(405, "method not allowed");
    }
  }

  const hostname = options.hostname ?? "127.0.0.1";
  const server = Bun.serve({ port: options.port ?? 0, hostname, fetch: handle });
  const managerUrl = `http://${hostname}:${server.port}`;
  return {
    url: storageUrl(managerUrl, options.instanceId),
    managerUrl,
    instanceId: options.instanceId,
    port: server.port!,
    stop: () => server.stop(true),
    stats,
  };
}

if (import.meta.main) {
  const args = process.argv.slice(2);
  const split = args.indexOf("--");
  const own = split === -1 ? args : args.slice(0, split);
  const command = split === -1 ? [] : args.slice(split + 1);
  const flag = (name: string) => {
    const at = own.indexOf(`--${name}`);
    return at === -1 ? undefined : own[at + 1];
  };
  const dir = flag("dir");
  const instanceId = flag("instance");
  const token = flag("token");
  if (!dir || !instanceId || !token) {
    console.error(
      "usage: bun dev-server.ts --dir <dir> --instance <id> --token <token> [--port <port>] [--host <host>] [--max-bytes <n>] [--verbose] [-- <command...>]",
    );
    process.exit(2);
  }
  const storage = startDevStorage({
    dir,
    instanceId,
    token,
    port: Number(flag("port") ?? 0),
    hostname: flag("host"),
    maxBytes: flag("max-bytes") ? Number(flag("max-bytes")) : undefined,
    verbose: own.includes("--verbose"),
  });
  console.log(`Dev MCP storage: ${storage.url} (files in ${path.resolve(dir)})`);
  if (command.length > 0) {
    const child = Bun.spawn(command, {
      stdio: ["inherit", "inherit", "inherit"],
      env: { ...process.env, MCP_MANAGER_URL: storage.managerUrl, MCP_INSTANCE_ID: instanceId, MCP_STORAGE_TOKEN: token },
    });
    for (const signal of ["SIGINT", "SIGTERM"] as const) process.on(signal, () => child.kill(signal));
    const code = await child.exited;
    storage.stop();
    process.exit(code);
  }
}
