/**
 * Webhook delivery of MCP Events (SEP-3415 draft): `events/subscribe`,
 * `events/unsubscribe`, and the dispatcher that posts each new event to every
 * subscription it matches.
 *
 * Subscriptions live in the app's own database next to the event log, so they
 * survive a restart and every process of the app sees the same ones. Each keeps
 * the log position it has been delivered through; a failed POST leaves the
 * position where it was and is retried with a backoff, so an event is delivered
 * at least once and in order. Requests are signed the Standard Webhooks way, as
 * the platform's own events server signs them (agentarea_streams
 * domain/mcp_events.py), and the platform's mcp_events source verifies them.
 */
import type { Database } from "bun:sqlite";
import { createHash, createHmac, randomBytes } from "node:crypto";
import type { AppStore, Migration } from "../store/store.ts";
import { headPosition, readEvents, type AppEvent } from "./log.ts";
import { encodeCursor, EventsError, EventsErrorCode, occurrence, type EventType, type Occurrence } from "./protocol.ts";

/** The subscriptions table. An app appends it to its MIGRATIONS once, after EVENT_LOG_MIGRATION. */
export const EVENT_SUBSCRIPTIONS_MIGRATION: Migration = (db) =>
  db.run(`
    CREATE TABLE app_event_subscriptions (
      id             TEXT PRIMARY KEY,
      name           TEXT NOT NULL,
      arguments      TEXT NOT NULL,
      url            TEXT NOT NULL,
      secret         TEXT NOT NULL,
      position       INTEGER NOT NULL,
      refresh_before TEXT NOT NULL,
      failures       INTEGER NOT NULL DEFAULT 0,
      retry_at       TEXT
    );
  `);

export const SUBSCRIPTION_HEADER = "X-MCP-Subscription-Id";
export const DEFAULT_TTL_MS = 60 * 60 * 1000;
export const MIN_TTL_MS = 60 * 1000;
export const MAX_TTL_MS = 24 * 60 * 60 * 1000;
/** Waits after the first failed POST, then the next; past the last the subscription is dropped. */
export const RETRY_DELAYS_MS = [30_000, 120_000, 600_000, 1_800_000, 3_600_000, 7_200_000];
const PAGE = 50;
const SECRET_PREFIX = "whsec_";

export type SubscribeParams = {
  name: string;
  arguments: Record<string, unknown>;
  url: string;
  secret: string;
  cursor: string | null;
  ttlMs: number | null;
};

export type UnsubscribeParams = { name: string; arguments: Record<string, unknown>; url: string };

export type Grant = { id: string; refreshBefore: string; cursor: string; truncated: boolean };

type Row = {
  id: string;
  name: string;
  arguments: string;
  url: string;
  secret: string;
  position: number;
  refresh_before: string;
  failures: number;
  retry_at: string | null;
};

const canonical = (value: Record<string, unknown>) =>
  JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))));

/** The subscription's key (event, arguments, url) as an id: subscribing again refreshes it. */
export const subscriptionId = (name: string, args: Record<string, unknown>, url: string) =>
  "sub_" + createHash("sha256").update(JSON.stringify([name, canonical(args), url])).digest("hex").slice(0, 32);

/** `webhook-signature`: `v1,` and the base64 HMAC-SHA256 over `id.timestamp.body`. */
export function sign(secret: string, messageId: string, timestamp: number, body: string): string {
  const key = Buffer.from(secret.slice(SECRET_PREFIX.length), "base64");
  return "v1," + createHmac("sha256", key).update(`${messageId}.${timestamp}.${body}`).digest("base64");
}

function validateSecret(secret: string): void {
  if (!secret.startsWith(SECRET_PREFIX)) throw new Error("delivery.secret must start with whsec_");
  const encoded = secret.slice(SECRET_PREFIX.length);
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) throw new Error("delivery.secret is not base64");
  const bytes = Buffer.from(encoded, "base64").length;
  if (bytes < 24 || bytes > 64) throw new Error("delivery.secret must encode 24 to 64 random bytes");
}

function validateUrl(raw: string): void {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("delivery.url is not a URL");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("delivery.url must be http(s)");
  if (url.username || url.password) throw new Error("delivery.url must not carry credentials");
}

function object(value: unknown, field: string): Record<string, unknown> {
  if (value == null) return {};
  if (typeof value !== "object" || Array.isArray(value)) throw new Error(`${field} must be an object`);
  return value as Record<string, unknown>;
}

/** `events/subscribe` params as they arrive, checked. */
export function parseSubscribeParams(raw: unknown): SubscribeParams {
  const params = object(raw, "params");
  if (typeof params.name !== "string" || params.name === "") throw new Error("name is required");
  const delivery = object(params.delivery, "delivery");
  if (delivery.mode != null && delivery.mode !== "webhook") throw new Error("delivery.mode must be webhook");
  if (typeof delivery.url !== "string") throw new Error("delivery.url is required");
  if (typeof delivery.secret !== "string") throw new Error("delivery.secret is required");
  validateUrl(delivery.url);
  validateSecret(delivery.secret);
  if (params.cursor != null && typeof params.cursor !== "string") throw new Error("cursor must be a string or null");
  if (params.ttlMs != null && (!Number.isInteger(params.ttlMs) || (params.ttlMs as number) < 0)) {
    throw new Error("ttlMs must be a non-negative integer");
  }
  return {
    name: params.name,
    arguments: object(params.arguments, "arguments"),
    url: delivery.url,
    secret: delivery.secret,
    cursor: (params.cursor as string | null | undefined) ?? null,
    ttlMs: (params.ttlMs as number | null | undefined) ?? null,
  };
}

/** `events/unsubscribe` params as they arrive, checked. */
export function parseUnsubscribeParams(raw: unknown): UnsubscribeParams {
  const params = object(raw, "params");
  if (typeof params.name !== "string" || params.name === "") throw new Error("name is required");
  const delivery = object(params.delivery, "delivery");
  if (typeof delivery.url !== "string") throw new Error("delivery.url is required");
  return { name: params.name, arguments: object(params.arguments, "arguments"), url: delivery.url };
}

function eventType(types: readonly EventType<never>[], name: string): EventType<unknown> {
  const type = types.find((t) => t.name === name) as EventType<unknown> | undefined;
  if (!type) {
    throw new EventsError(EventsErrorCode.NotFound, `no event ${JSON.stringify(name)}; this server offers ${types.map((t) => t.name).join(", ")}`, {
      kind: "event",
    });
  }
  return type;
}

function parseArguments(type: EventType<unknown>, raw: Record<string, unknown>): unknown {
  try {
    return type.parseArguments(raw);
  } catch (error) {
    throw new EventsError(EventsErrorCode.InvalidParams, `arguments do not match the event's inputSchema: ${(error as Error).message}`);
  }
}

/** Whether `params` names a subscription that exists with the same secret, so its endpoint was proven already. */
export function isKnownEndpoint(db: Database, params: SubscribeParams): boolean {
  const id = subscriptionId(params.name, params.arguments, params.url);
  const row = db.query<{ secret: string }, [string]>("SELECT secret FROM app_event_subscriptions WHERE id = ?").get(id);
  return row?.secret === params.secret;
}

/** Checks a subscription's event and arguments without writing; throws the EventsError the client gets. */
export function checkSubscription(types: readonly EventType<never>[], params: SubscribeParams): void {
  parseArguments(eventType(types, params.name), params.arguments);
}

/** Creates or refreshes the subscription, starting at `cursor` (or now), and answers the grant. */
export function subscribe(db: Database, types: readonly EventType<never>[], params: SubscribeParams, now: Date = new Date()): Grant {
  checkSubscription(types, params);
  const id = subscriptionId(params.name, params.arguments, params.url);
  const ttl = params.ttlMs == null ? MAX_TTL_MS : Math.min(Math.max(params.ttlMs, MIN_TTL_MS), MAX_TTL_MS);
  const refreshBefore = new Date(now.getTime() + ttl).toISOString();
  const existing = db.query<{ position: number }, [string]>("SELECT position FROM app_event_subscriptions WHERE id = ?").get(id);
  let position = existing?.position ?? headPosition(db);
  if (params.cursor !== null) {
    const match = /^v1:(\d+)$/.exec(params.cursor);
    if (!match) throw new EventsError(EventsErrorCode.InvalidParams, `cursor ${JSON.stringify(params.cursor)} is not one this server issued`);
    position = Math.max(Number(match[1]), existing?.position ?? 0);
  }
  const pruned = db.query<{ through: number }, []>("SELECT through FROM app_events_pruned WHERE id = 1").get();
  db.run(
    `INSERT INTO app_event_subscriptions (id, name, arguments, url, secret, position, refresh_before)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (id) DO UPDATE SET secret = excluded.secret, position = excluded.position,
       refresh_before = excluded.refresh_before, failures = 0, retry_at = NULL`,
    [id, params.name, canonical(params.arguments), params.url, params.secret, position, refreshBefore],
  );
  return { id, refreshBefore, cursor: encodeCursor(position), truncated: (pruned?.through ?? 0) > position };
}

/** Removes the subscription; unknown ones are not an error. */
export function unsubscribe(db: Database, params: UnsubscribeParams): void {
  db.run("DELETE FROM app_event_subscriptions WHERE id = ?", [subscriptionId(params.name, params.arguments, params.url)]);
}

type Delivery = {
  id: string;
  url: string;
  secret: string;
  failures: number;
  events: { seq: number; occurrence: Occurrence }[];
  /** Where the subscription stands once every event of the page is delivered. */
  position: number;
  hasMore: boolean;
};

/** The next page of events for every live subscription that is not waiting out a retry. */
export function pendingDeliveries(db: Database, types: readonly EventType<never>[], now: Date): Delivery[] {
  const rows = db
    .query<Row, [string, string]>(
      "SELECT * FROM app_event_subscriptions WHERE refresh_before > ? AND (retry_at IS NULL OR retry_at <= ?) ORDER BY id",
    )
    .all(now.toISOString(), now.toISOString());
  const deliveries: Delivery[] = [];
  for (const row of rows) {
    const type = types.find((t) => t.name === row.name) as EventType<unknown> | undefined;
    if (!type) continue;
    const args = type.parseArguments(JSON.parse(row.arguments) as Record<string, unknown>);
    const page = readEvents(db, { name: row.name, after: row.position, limit: PAGE, admits: (data) => type.admits(args, data) });
    if (page.position === row.position && page.events.length === 0) continue;
    deliveries.push({
      id: row.id,
      url: row.url,
      secret: row.secret,
      failures: row.failures,
      events: page.events.map((event: AppEvent) => ({ seq: event.seq, occurrence: occurrence(event) })),
      position: page.position,
      hasMore: page.hasMore,
    });
  }
  return deliveries;
}

type Outcome = { id: string; secret: string; position: number; failed: boolean; drop: boolean; failures: number };

/** Writes what a round of deliveries achieved; a subscription changed meanwhile is left alone. */
export function recordDeliveries(db: Database, outcomes: readonly Outcome[], now: Date): void {
  db.run("DELETE FROM app_event_subscriptions WHERE refresh_before <= ?", [now.toISOString()]);
  for (const outcome of outcomes) {
    if (outcome.drop) {
      db.run("DELETE FROM app_event_subscriptions WHERE id = ? AND secret = ?", [outcome.id, outcome.secret]);
      continue;
    }
    const retryAt = outcome.failed ? new Date(now.getTime() + RETRY_DELAYS_MS[outcome.failures - 1]!).toISOString() : null;
    db.run(
      `UPDATE app_event_subscriptions SET position = MAX(position, ?), failures = ?, retry_at = ?
       WHERE id = ? AND secret = ?`,
      [outcome.position, outcome.failed ? outcome.failures : 0, retryAt, outcome.id, outcome.secret],
    );
  }
}

type Fetch = (url: string, init: { method: string; headers: Record<string, string>; body: string }) => Promise<Response>;

/** One signed POST of `body` to a subscription's endpoint. */
export function post(fetchFn: Fetch, target: { url: string; secret: string; id: string }, messageId: string, body: unknown, now: Date) {
  const raw = JSON.stringify(body);
  const timestamp = Math.floor(now.getTime() / 1000);
  return fetchFn(target.url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "webhook-id": messageId,
      "webhook-timestamp": String(timestamp),
      "webhook-signature": sign(target.secret, messageId, timestamp, raw),
      [SUBSCRIPTION_HEADER]: target.id,
    },
    body: raw,
  });
}

/** Proves the endpoint wants deliveries: it must echo a one-time nonce in a 2xx answer. */
export async function challenge(fetchFn: Fetch, target: { url: string; secret: string; id: string }, now: Date = new Date()): Promise<void> {
  const nonce = randomBytes(12).toString("hex");
  let echoed: unknown;
  try {
    const response = await post(fetchFn, target, `msg_verification_${randomBytes(12).toString("hex")}`, { type: "verification", challenge: nonce }, now);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    echoed = ((await response.json()) as { challenge?: unknown }).challenge;
  } catch (error) {
    throw new EventsError(EventsErrorCode.CallbackError, "the callback endpoint did not answer the challenge", { reason: (error as Error).message });
  }
  if (echoed !== nonce) {
    throw new EventsError(EventsErrorCode.CallbackError, "the callback endpoint did not echo the challenge", { reason: "challenge_failed" });
  }
}

/** A POST answered with one of these will never be accepted: the subscription is dropped. */
const FINAL_STATUSES = new Set([404, 410]);

/**
 * Posts new events to their subscriptions. One per process: `kick()` after a
 * write delivers it right away, and `start()` retries failed POSTs on a timer.
 */
export class EventDispatcher {
  readonly #app: AppStore;
  readonly #types: readonly EventType<never>[];
  readonly #fetch: Fetch;
  readonly #now: () => Date;
  #running: Promise<void> | null = null;
  #again = false;

  constructor(options: { app: AppStore; types: readonly EventType<never>[]; fetch?: Fetch; now?: () => Date }) {
    this.#app = options.app;
    this.#types = options.types;
    this.#fetch = options.fetch ?? ((url, init) => fetch(url, init));
    this.#now = options.now ?? (() => new Date());
  }

  get fetch(): Fetch {
    return this.#fetch;
  }

  /** Retries on a timer that does not keep the process alive. */
  start(intervalMs: number = RETRY_DELAYS_MS[0]!): void {
    setInterval(() => this.kick(), intervalMs).unref();
  }

  /** Delivers whatever is pending, soon; a kick during a round runs one more round after it. */
  kick(): void {
    if (this.#running) {
      this.#again = true;
      return;
    }
    this.#running = this.#loop().finally(() => {
      this.#running = null;
    });
  }

  /** Resolves when no round is running. */
  async idle(): Promise<void> {
    while (this.#running) await this.#running;
  }

  async #loop(): Promise<void> {
    do {
      this.#again = false;
      try {
        if (await this.flush()) this.#again = true;
      } catch (error) {
        console.error("Event delivery round failed:", error);
      }
    } while (this.#again);
  }

  /** One round: posts each pending page and records how far each got. Answers whether more is pending. */
  async flush(): Promise<boolean> {
    const now = this.#now();
    const deliveries = await this.#app.read((db) => pendingDeliveries(db, this.#types, now));
    if (deliveries.length === 0) return false;
    const outcomes: Outcome[] = [];
    let more = false;
    for (const delivery of deliveries) {
      let position = delivery.position;
      let failed = false;
      let drop = false;
      let delivered = delivery.events.length === 0 ? delivery.position : delivery.events[0]!.seq - 1;
      for (const { seq, occurrence: body } of delivery.events) {
        let response: Response | null = null;
        try {
          response = await post(this.#fetch, delivery, body.eventId, body, now);
        } catch (error) {
          console.error(`Delivering ${body.eventId} to subscription ${delivery.id} failed:`, error);
        }
        if (response?.ok) {
          delivered = seq;
          continue;
        }
        if (response) console.error(`Subscription ${delivery.id} answered ${body.eventId} with HTTP ${response.status}`);
        drop = response !== null && FINAL_STATUSES.has(response.status);
        failed = true;
        position = delivered;
        break;
      }
      const failures = failed ? delivery.failures + 1 : 0;
      if (failed && failures > RETRY_DELAYS_MS.length) drop = true;
      outcomes.push({ id: delivery.id, secret: delivery.secret, position, failed, drop, failures });
      if (!failed && delivery.hasMore) more = true;
    }
    await this.#app.transact((db) => recordDeliveries(db, outcomes, now));
    return more;
  }
}
