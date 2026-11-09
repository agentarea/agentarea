import { Database } from "bun:sqlite";
import { afterAll, beforeEach, describe, expect, test } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { startDevStorage, type DevStorage } from "../store/dev-server.ts";
import { openAppStore, type AppStore } from "../store/store.ts";
import { appendEvent, EVENT_LOG_MIGRATION } from "./log.ts";
import { EventsError, EventsErrorCode, type EventType } from "./protocol.ts";
import {
  challenge,
  EVENT_SUBSCRIPTIONS_MIGRATION,
  EventDispatcher,
  parseSubscribeParams,
  RETRY_DELAYS_MS,
  sign,
  subscribe,
  unsubscribe,
} from "./subscriptions.ts";

const SECRET = "whsec_MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="; // pragma: allowlist secret
const URL = "https://api.example.test/v1/webhooks/src-1";

const assigned: EventType<{ assignee?: string }> = {
  name: "task.assigned",
  title: "Task assigned",
  description: "A task got an assignee",
  inputSchema: { type: "object" },
  payloadSchema: { type: "object" },
  parseArguments(raw) {
    if (raw.assignee !== undefined && typeof raw.assignee !== "string") throw new Error("assignee must be a string");
    return { assignee: raw.assignee as string | undefined };
  },
  admits: (args, data) => args.assignee === undefined || data.assignee === args.assignee,
};
const types = [assigned] as EventType<never>[];

const params = (extra: Record<string, unknown> = {}) =>
  parseSubscribeParams({ name: "task.assigned", arguments: {}, delivery: { url: URL, secret: SECRET }, ...extra });

function memoryDb(): Database {
  const db = new Database(":memory:");
  EVENT_LOG_MIGRATION(db);
  EVENT_SUBSCRIPTIONS_MIGRATION(db);
  return db;
}

describe("signing", () => {
  test("matches the platform's Standard Webhooks signature", () => {
    // agentarea_streams.domain.mcp_events.sign with the same inputs.
    expect(sign(SECRET, "evt-1", 1792000000, '{"a":1}')).toBe("v1,1RlGb0VgpkmJnA2HhmxVNWojOMMT3dOimOq0eHrDCDc=");
  });
});

describe("events/subscribe", () => {
  test("refuses a delivery the platform could not verify", () => {
    expect(() => params({ delivery: { url: URL, secret: "plain" } })).toThrow("whsec_");
    expect(() => params({ delivery: { url: "ftp://x", secret: SECRET } })).toThrow("http(s)");
    expect(() => params({ delivery: { url: URL, secret: SECRET, mode: "push" } })).toThrow("webhook");
  });

  test("starts at now, resumes at a cursor, and a repeat refreshes the same subscription", () => {
    const db = memoryDb();
    appendEvent(db, "task.assigned", { assignee: "a" });
    const now = new Date("2026-10-29T10:00:00Z");
    const first = subscribe(db, types, params({ ttlMs: 10 }), now);
    expect(first.cursor).toBe("v1:1");
    expect(first.refreshBefore).toBe("2026-10-29T10:01:00.000Z");
    const again = subscribe(db, types, params({ cursor: "v1:0" }), now);
    expect(again.id).toBe(first.id);
    expect(again.cursor).toBe("v1:1");
    expect(again.refreshBefore).toBe("2026-10-30T10:00:00.000Z");
    expect((db.query("SELECT COUNT(*) AS n FROM app_event_subscriptions").get() as { n: number }).n).toBe(1);
    unsubscribe(db, { name: "task.assigned", arguments: {}, url: URL });
    expect((db.query("SELECT COUNT(*) AS n FROM app_event_subscriptions").get() as { n: number }).n).toBe(0);
  });

  test("names an unknown event and bad arguments with the extension's codes", () => {
    const db = memoryDb();
    const code = (fn: () => unknown) => {
      try {
        fn();
      } catch (error) {
        return (error as EventsError).code;
      }
    };
    expect(code(() => subscribe(db, types, params({ name: "nope" })))).toBe(EventsErrorCode.NotFound);
    expect(code(() => subscribe(db, types, params({ arguments: { assignee: 1 } })))).toBe(EventsErrorCode.InvalidParams);
  });
});

type Posted = { url: string; headers: Record<string, string>; body: Record<string, unknown> };

function fakeEndpoint(answer: (body: Record<string, unknown>) => Response) {
  const posted: Posted[] = [];
  const fetchFn = async (url: string, init: { headers: Record<string, string>; body: string }) => {
    const body = JSON.parse(init.body) as Record<string, unknown>;
    posted.push({ url, headers: init.headers, body });
    return answer(body);
  };
  return { posted, fetchFn };
}

describe("challenge", () => {
  test("passes only when the endpoint echoes the nonce", async () => {
    const echo = fakeEndpoint((body) => Response.json({ challenge: body.challenge }));
    await challenge(echo.fetchFn, { url: URL, secret: SECRET, id: "sub_1" });
    expect(echo.posted[0]!.body.type).toBe("verification");
    expect(echo.posted[0]!.headers["X-MCP-Subscription-Id"]).toBe("sub_1");

    const deaf = fakeEndpoint(() => Response.json({}));
    await expect(challenge(deaf.fetchFn, { url: URL, secret: SECRET, id: "sub_1" })).rejects.toThrow("did not echo");
    const down = fakeEndpoint(() => new Response("", { status: 502 }));
    await expect(challenge(down.fetchFn, { url: URL, secret: SECRET, id: "sub_1" })).rejects.toThrow("did not answer");
  });
});

describe("dispatcher", () => {
  let storage: DevStorage;
  let app: AppStore;
  let now = new Date("2026-10-29T10:00:00Z");

  beforeEach(async () => {
    storage?.stop();
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "events-sub-"));
    storage = startDevStorage({ dir, instanceId: "inst-1", token: "t", maxBytes: 1024 * 1024 });
    app = await openAppStore({
      file: "app.sqlite",
      migrations: [EVENT_LOG_MIGRATION, EVENT_SUBSCRIPTIONS_MIGRATION],
      env: { MCP_MANAGER_URL: storage.managerUrl, MCP_INSTANCE_ID: storage.instanceId, MCP_STORAGE_TOKEN: "t" },
    });
    now = new Date("2026-10-29T10:00:00Z");
  });
  afterAll(() => storage?.stop());

  const dispatcher = (fetchFn: ReturnType<typeof fakeEndpoint>["fetchFn"]) =>
    new EventDispatcher({ app, types, fetch: fetchFn, now: () => now });

  test("posts each matching event once, in order, signed, as the occurrence the poll would give", async () => {
    const endpoint = fakeEndpoint(() => new Response(null, { status: 204 }));
    await app.transact((db) => subscribe(db, types, params({ arguments: { assignee: "ops-bot" } }), now));
    await app.transact((db) => {
      appendEvent(db, "task.assigned", { key: "OPS-1", assignee: "ops-bot" });
      appendEvent(db, "task.assigned", { key: "OPS-2", assignee: "maya" });
      appendEvent(db, "task.assigned", { key: "OPS-3", assignee: "ops-bot" });
    });
    const d = dispatcher(endpoint.fetchFn);
    d.kick();
    await d.idle();
    d.kick();
    await d.idle();
    expect(endpoint.posted.map((p) => (p.body.data as { key: string }).key)).toEqual(["OPS-1", "OPS-3"]);
    const first = endpoint.posted[0]!;
    expect(first.headers["webhook-id"]).toBe(first.body.eventId as string);
    expect(first.headers["webhook-signature"]).toBe(
      sign(SECRET, first.headers["webhook-id"]!, Number(first.headers["webhook-timestamp"]), JSON.stringify(first.body)),
    );
    expect((first.body.data as { kind: string }).kind).toBe("task.assigned");
  });

  test("a failed POST keeps the event and retries it after the backoff", async () => {
    let up = false;
    const endpoint = fakeEndpoint(() => new Response(null, { status: up ? 200 : 503 }));
    await app.transact((db) => subscribe(db, types, params(), now));
    await app.transact((db) => appendEvent(db, "task.assigned", { key: "OPS-1" }));
    const d = dispatcher(endpoint.fetchFn);
    await d.flush();
    up = true;
    await d.flush();
    expect(endpoint.posted).toHaveLength(1);
    now = new Date(now.getTime() + RETRY_DELAYS_MS[0]!);
    await d.flush();
    expect(endpoint.posted).toHaveLength(2);
    await d.flush();
    expect(endpoint.posted).toHaveLength(2);
  });

  test("an endpoint that answers 410 loses its subscription", async () => {
    const endpoint = fakeEndpoint(() => new Response(null, { status: 410 }));
    await app.transact((db) => subscribe(db, types, params(), now));
    await app.transact((db) => appendEvent(db, "task.assigned", { key: "OPS-1" }));
    await dispatcher(endpoint.fetchFn).flush();
    expect(await app.read((db) => (db.query("SELECT COUNT(*) AS n FROM app_event_subscriptions").get() as { n: number }).n)).toBe(0);
  });

  test("an expired subscription gets nothing and is removed", async () => {
    const endpoint = fakeEndpoint(() => new Response(null, { status: 200 }));
    await app.transact((db) => subscribe(db, types, params({ ttlMs: 60_000 }), now));
    await app.transact((db) => appendEvent(db, "task.assigned", { key: "OPS-1" }));
    now = new Date(now.getTime() + 61_000);
    await dispatcher(endpoint.fetchFn).flush();
    expect(endpoint.posted).toHaveLength(0);
  });
});
