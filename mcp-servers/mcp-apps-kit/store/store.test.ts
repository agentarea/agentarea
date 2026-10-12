import type { Database } from "bun:sqlite";
import { afterAll, beforeEach, describe, expect, test } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { StorageClient } from "./client.ts";
import { startDevStorage, type DevStorage } from "./dev-server.ts";
import { readRows, syncRows, type Table } from "./rows.ts";
import { openAppStore, type Migration } from "./store.ts";

const TOKEN = "test-token";
let storage: DevStorage;
let dir: string;

beforeEach(() => {
  storage?.stop();
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "app-store-"));
  storage = startDevStorage({ dir, instanceId: "inst-1", token: TOKEN, maxBytes: 1024 * 1024 });
});
afterAll(() => storage?.stop());

const env = (extra: Record<string, string> = {}) => ({
  MCP_MANAGER_URL: storage.managerUrl,
  MCP_INSTANCE_ID: storage.instanceId,
  MCP_STORAGE_TOKEN: TOKEN,
  ...extra,
});

const counterSchema: Migration[] = [
  (db) => {
    db.run("CREATE TABLE counter (id INTEGER PRIMARY KEY CHECK (id = 1), n INTEGER NOT NULL)");
    db.run("INSERT INTO counter (id, n) VALUES (1, 0)");
  },
  (db) => db.run("CREATE TABLE events (id INTEGER PRIMARY KEY, writer TEXT NOT NULL, n INTEGER NOT NULL)"),
];
const count = (db: Database) => (db.query("SELECT n FROM counter").get() as { n: number }).n;

describe("dev storage server", () => {
  const object = () => `${storage.url}/objects/app.sqlite`;
  const auth = { Authorization: `Bearer ${TOKEN}` };

  test("refuses a missing or wrong token", async () => {
    expect((await fetch(object(), { method: "HEAD" })).status).toBe(401);
    expect((await fetch(object(), { headers: { Authorization: "Bearer nope" } })).status).toBe(401);
  });

  test("refuses another instance's path", async () => {
    const other = `${storage.managerUrl}/mcp/inst-2/storage/objects/app.sqlite`;
    expect((await fetch(other, { headers: auth })).status).toBe(403);
    await expect(
      openAppStore({ file: "app.sqlite", migrations: counterSchema, env: { ...env(), MCP_INSTANCE_ID: "inst-2" } }),
    ).rejects.toThrow(/refused the token \(403/);
  });

  test("a PUT without a precondition gets 428, and the client refuses to send one", async () => {
    const response = await fetch(object(), { method: "PUT", headers: auth, body: "x" });
    expect(response.status).toBe(428);
    expect((await fetch(object(), { method: "HEAD", headers: auth })).status).toBe(404);
  });

  test("create once, update by ETag, stale ETag gets 412", async () => {
    const client = new StorageClient(storage.url, TOKEN);
    const created = await client.put("app.sqlite", new Uint8Array([1]), { ifNoneMatch: "*" }, "application/octet-stream");
    expect(created.ok).toBe(true);
    const etag = (created as { etag: string }).etag;
    expect(await client.put("app.sqlite", new Uint8Array([2]), { ifNoneMatch: "*" }, "x")).toEqual({ ok: false, status: 412 });
    const updated = await client.put("app.sqlite", new Uint8Array([3]), { ifMatch: etag }, "x");
    expect(updated.ok).toBe(true);
    expect(await client.put("app.sqlite", new Uint8Array([4]), { ifMatch: etag }, "x")).toEqual({ ok: false, status: 412 });
    expect(await client.head("app.sqlite")).toBe((updated as { etag: string }).etag);
    expect([...(await client.get("app.sqlite"))!.bytes]).toEqual([3]);
  });

  test("rejects bad paths and bodies over the limit", async () => {
    expect((await fetch(`${storage.url}/objects/a%2F..%2Fb`, { headers: auth })).status).toBe(400);
    expect((await fetch(`${storage.url}/objects/a//b`, { headers: auth })).status).toBe(400);
    const big = new Uint8Array(1024 * 1024 + 1);
    const response = await fetch(object(), { method: "PUT", headers: { ...auth, "If-None-Match": "*" }, body: big });
    expect(response.status).toBe(413);
  });

  test("lists objects under a prefix", async () => {
    const client = new StorageClient(storage.url, TOKEN);
    await client.put("a/one", new Uint8Array([1]), { ifNoneMatch: "*" }, "x");
    await client.put("b/two", new Uint8Array([1, 2]), { ifNoneMatch: "*" }, "x");
    const listed = (await (await fetch(`${storage.url}/objects?prefix=a/`, { headers: auth })).json()) as {
      objects: { path: string; size: number }[];
    };
    expect(listed.objects.map((o) => [o.path, o.size])).toEqual([["a/one", 1]]);
  });
});

describe("app store", () => {
  test("fails at open without storage env", async () => {
    await expect(openAppStore({ file: "app.sqlite", migrations: counterSchema, env: {} })).rejects.toThrow(
      /MCP_MANAGER_URL, MCP_INSTANCE_ID, MCP_STORAGE_TOKEN must be set/,
    );
    await expect(
      openAppStore({ file: "app.sqlite", migrations: counterSchema, env: { ...env(), MCP_STORAGE_TOKEN: "" } }),
    ).rejects.toThrow(/MCP_STORAGE_TOKEN must be set/);
  });

  test("fails at open with a wrong token", async () => {
    await expect(
      openAppStore({ file: "app.sqlite", migrations: counterSchema, env: { ...env(), MCP_STORAGE_TOKEN: "x" } }),
    ).rejects.toThrow(/refused the token/);
  });

  test("two processes, concurrent transactions: no lost updates", async () => {
    const a = await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    const b = await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    const bump = (writer: string) => (db: Database) => {
      const n = count(db) + 1;
      db.run("UPDATE counter SET n = ?", [n]);
      db.run("INSERT INTO events (writer, n) VALUES (?, ?)", [writer, n]);
      return n;
    };
    const runs = 25;
    const results = await Promise.all(
      Array.from({ length: runs }, (_, i) => [a.transact(bump(`a${i}`)), b.transact(bump(`b${i}`))]).flat(),
    );
    expect(results.toSorted((x, y) => x - y)).toEqual(Array.from({ length: runs * 2 }, (_, i) => i + 1));
    expect(await a.read(count)).toBe(runs * 2);
    expect(await b.read(count)).toBe(runs * 2);
    const writers = await b.read((db) => db.query("SELECT writer FROM events ORDER BY n").all().length);
    expect(writers).toBe(runs * 2);
    expect(a.conflicts + b.conflicts).toBeGreaterThan(0);
    expect(storage.stats.conflicts).toBe(a.conflicts + b.conflicts);
  });

  test("a read sees another process's write", async () => {
    const a = await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    const b = await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    await a.transact((db) => db.run("UPDATE counter SET n = 41"));
    expect(await b.read(count)).toBe(41);
  });

  test("a throwing transaction writes nothing", async () => {
    const store = await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    const puts = storage.stats.puts;
    await expect(
      store.transact((db) => {
        db.run("UPDATE counter SET n = 99");
        throw new Error("rejected");
      }),
    ).rejects.toThrow("rejected");
    expect(storage.stats.puts).toBe(puts);
    expect(await store.read(count)).toBe(0);
  });

  test("a transaction that changes nothing is not written", async () => {
    const store = await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    const puts = storage.stats.puts;
    expect(await store.transact(count)).toBe(0);
    expect(storage.stats.puts).toBe(puts);
    await store.transact((db) => db.run("UPDATE counter SET n = n + 1"));
    expect(storage.stats.puts).toBe(puts + 1);
  });

  test("an async transaction body is refused", async () => {
    const store = await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    await expect(store.transact(async () => 1)).rejects.toThrow(/synchronous/);
  });

  test("migrations run in order, once, from the stored version", async () => {
    const order: number[] = [];
    const step = (n: number): Migration => (db) => {
      order.push(n);
      db.run(`CREATE TABLE IF NOT EXISTS log (n INTEGER)`);
      db.run("INSERT INTO log (n) VALUES (?)", [n]);
    };
    const first = await openAppStore({ file: "app.sqlite", migrations: [step(1), step(2)], env: env() });
    expect(first.schemaVersion).toBe(2);
    expect(order).toEqual([1, 2]);
    const later = await openAppStore({ file: "app.sqlite", migrations: [step(1), step(2), step(3), step(4)], env: env() });
    expect(later.schemaVersion).toBe(4);
    expect(order).toEqual([1, 2, 3, 4]);
    expect(await later.read((db) => db.query("SELECT n FROM log ORDER BY rowid").all())).toEqual([{ n: 1 }, { n: 2 }, { n: 3 }, { n: 4 }]);
    await openAppStore({ file: "app.sqlite", migrations: [step(1), step(2), step(3), step(4)], env: env() });
    expect(order).toEqual([1, 2, 3, 4]);
  });

  test("once a newer process migrates, an older one stops writing", async () => {
    const v1 = await openAppStore({ file: "app.sqlite", migrations: counterSchema.slice(0, 1), env: env() });
    const v2 = await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    expect(v2.schemaVersion).toBe(2);
    await expect(v1.transact((db) => db.run("UPDATE counter SET n = 1"))).rejects.toThrow(/schema version 2, newer than this app knows \(1\)/);
  });

  test("a database newer than the code is read-only", async () => {
    await openAppStore({ file: "app.sqlite", migrations: counterSchema, env: env() });
    const old = await openAppStore({ file: "app.sqlite", migrations: counterSchema.slice(0, 1), env: env() });
    expect(old.schemaVersion).toBe(2);
    expect(await old.read(count)).toBe(0);
    await expect(old.transact((db) => db.run("UPDATE counter SET n = 5"))).rejects.toThrow(/writes are refused/);
    await expect(old.read((db) => db.run("UPDATE counter SET n = 5"))).rejects.toThrow(/readonly/);
  });

  test("demo seed: only with AGENTAREA_MCP_SEED_DEMO=1 and only into a new database", async () => {
    let seeded = 0;
    const seed: Migration = (db) => {
      seeded += 1;
      db.run("UPDATE counter SET n = 100");
    };
    const plain = await openAppStore({ file: "plain.sqlite", migrations: counterSchema, seed, env: env() });
    expect(await plain.read(count)).toBe(0);
    const other = await openAppStore({ file: "plain.sqlite", migrations: counterSchema, seed, env: env({ AGENTAREA_MCP_SEED_DEMO: "1" }) });
    expect(await other.read(count)).toBe(0);
    expect(seeded).toBe(0);
    const demo = await openAppStore({ file: "demo.sqlite", migrations: counterSchema, seed, env: env({ AGENTAREA_MCP_SEED_DEMO: "1" }) });
    expect(await demo.read(count)).toBe(100);
    await openAppStore({ file: "demo.sqlite", migrations: counterSchema, seed, env: env({ AGENTAREA_MCP_SEED_DEMO: "1" }) });
    expect(seeded).toBe(1);
    await openAppStore({ file: "other.sqlite", migrations: counterSchema, seed, env: env({ AGENTAREA_MCP_SEED_DEMO: "true" }) });
    expect(seeded).toBe(1);
  });

  test("two processes racing to create: one seed, the other adopts it", async () => {
    let seeded = 0;
    const seed: Migration = (db) => {
      seeded += 1;
      db.run("UPDATE counter SET n = n + 1");
    };
    const options = { file: "race.sqlite", migrations: counterSchema, seed, env: env({ AGENTAREA_MCP_SEED_DEMO: "1" }) };
    const [a, b] = await Promise.all([openAppStore(options), openAppStore(options)]);
    expect(await a.read(count)).toBe(1);
    expect(await b.read(count)).toBe(1);
    expect(seeded).toBeGreaterThanOrEqual(1);
  });
});

describe("rows", () => {
  const tables: Table[] = [
    { name: "parent", columns: ["id", "name"], key: ["id"] },
    { name: "child", columns: ["parent_id", "position", "label"], key: ["parent_id", "position"], orderBy: "parent_id, position" },
  ];
  const schema: Migration[] = [
    (db) => {
      db.run("CREATE TABLE parent (id TEXT PRIMARY KEY, name TEXT NOT NULL)");
      db.run(
        "CREATE TABLE child (parent_id TEXT NOT NULL REFERENCES parent(id), position INTEGER NOT NULL, label TEXT NOT NULL, PRIMARY KEY (parent_id, position))",
      );
    },
  ];

  test("syncRows writes only the difference and keeps foreign keys", async () => {
    const store = await openAppStore({ file: "rows.sqlite", migrations: schema, env: env() });
    await store.transact((db) => {
      const before = readRows(db, tables);
      return syncRows(db, tables, before, {
        parent: [{ id: "p1", name: "one" }, { id: "p2", name: "two" }],
        child: [{ parent_id: "p1", position: 0, label: "a" }, { parent_id: "p2", position: 0, label: "b" }],
      });
    });
    const changed = await store.transact((db) => {
      const before = readRows(db, tables);
      return syncRows(db, tables, before, {
        parent: [{ id: "p1", name: "uno" }],
        child: [{ parent_id: "p1", position: 0, label: "a" }, { parent_id: "p1", position: 1, label: "c" }],
      });
    });
    expect(changed).toBe(4);
    expect(await store.read((db) => readRows(db, tables))).toEqual({
      parent: [{ id: "p1", name: "uno" }],
      child: [{ parent_id: "p1", position: 0, label: "a" }, { parent_id: "p1", position: 1, label: "c" }],
    });
    await expect(
      store.transact((db) => syncRows(db, tables, readRows(db, tables), { parent: [], child: [{ parent_id: "p1", position: 0, label: "a" }] })),
    ).rejects.toThrow(/FOREIGN KEY/);
  });
});
