/**
 * MCP Events (SEP-3415 draft, protocol 2026-07-28) served from an app's event
 * log: `events/list` and `events/poll`. Poll delivery only: an app's MCP
 * server is stateless, so it keeps no subscriptions to push to.
 *
 * Wire shapes follow the platform's own events server
 * (agentarea-platform agentarea_api/mcp_events.py) and the client that polls
 * it (agentarea-event-service internal/mcpevents).
 */
import type { Database } from "bun:sqlite";
import { headPosition, readEvents, type AppEvent, type EventData } from "./log.ts";

export const EVENTS_EXTENSION = "io.modelcontextprotocol/events";
export const EVENTS_SETTINGS = { listChanged: false };

export const NEXT_POLL_MS = 10_000;
export const DEFAULT_MAX_EVENTS = 50;
export const MAX_EVENTS = 500;

export enum EventsErrorCode {
  InvalidParams = -32602,
  NotFound = -32023,
}

export class EventsError extends Error {
  constructor(
    readonly code: EventsErrorCode,
    message: string,
    readonly data?: Record<string, unknown>,
  ) {
    super(message);
  }
}

/** One event an app offers: what `events/list` shows, and how a subscriber's arguments narrow it. */
export type EventType<A = unknown> = {
  name: string;
  title: string;
  description: string;
  /** JSON Schema of the arguments a subscriber may pass. */
  inputSchema: Record<string, unknown>;
  /** JSON Schema of an occurrence's `data`. */
  payloadSchema: Record<string, unknown>;
  /** Checks a subscriber's arguments; throws an Error that says what is wrong. */
  parseArguments(raw: Record<string, unknown>): A;
  admits(args: A, data: EventData): boolean;
};

export type PollParams = {
  name: string;
  arguments?: Record<string, unknown> | null;
  /** null starts from now. */
  cursor?: string | null;
  maxEvents?: number;
  maxAgeMs?: number;
};

export type Occurrence = { eventId: string; name: string; timestamp: string; data: EventData };

export type PollResult = {
  events: Occurrence[];
  cursor: string;
  truncated: boolean;
  hasMore: boolean;
  nextPollMs: number;
};

const CURSOR = /^v1:(\d+)$/;

export const encodeCursor = (position: number) => `v1:${position}`;

function decodeCursor(cursor: string): number {
  const match = CURSOR.exec(cursor);
  if (!match) throw new EventsError(EventsErrorCode.InvalidParams, `cursor ${JSON.stringify(cursor)} is not one this server issued`);
  return Number(match[1]);
}

export function listEvents(types: readonly EventType<never>[]): { events: Record<string, unknown>[] } {
  return {
    events: types.map((t) => ({
      name: t.name,
      title: t.title,
      description: t.description,
      delivery: ["poll"],
      inputSchema: t.inputSchema,
      payloadSchema: t.payloadSchema,
    })),
  };
}

/** The occurrence a client receives: `data.kind` names the event and `data.id` identifies it. */
export const occurrence = (event: AppEvent): Occurrence => ({
  eventId: event.id,
  name: event.name,
  timestamp: event.at,
  data: { ...event.data, id: event.id, kind: event.name },
});

export function pollEvents(db: Database, types: readonly EventType<never>[], params: PollParams, now: Date = new Date()): PollResult {
  const type = types.find((t) => t.name === params.name) as EventType<unknown> | undefined;
  if (!type) {
    throw new EventsError(EventsErrorCode.NotFound, `no event ${JSON.stringify(params.name)}; this server offers ${types.map((t) => t.name).join(", ")}`, {
      kind: "event",
    });
  }
  let args: unknown;
  try {
    args = type.parseArguments(params.arguments ?? {});
  } catch (error) {
    throw new EventsError(EventsErrorCode.InvalidParams, `arguments do not match the event's inputSchema: ${(error as Error).message}`);
  }
  if (params.cursor == null) {
    return { events: [], cursor: encodeCursor(headPosition(db)), truncated: false, hasMore: false, nextPollMs: NEXT_POLL_MS };
  }
  const after = decodeCursor(params.cursor);
  const floor = params.maxAgeMs == null ? null : new Date(now.getTime() - params.maxAgeMs).toISOString();
  let aged = false;
  const page = readEvents(db, {
    name: type.name,
    after,
    limit: Math.min(params.maxEvents ?? DEFAULT_MAX_EVENTS, MAX_EVENTS),
    admits: (data, event) => {
      if (floor !== null && event.at < floor) {
        aged = true;
        return false;
      }
      return type.admits(args, data);
    },
  });
  return {
    events: page.events.map(occurrence),
    cursor: encodeCursor(page.position),
    truncated: page.truncated || aged,
    hasMore: page.hasMore,
    nextPollMs: NEXT_POLL_MS,
  };
}

function record(value: unknown, field: string): Record<string, unknown> | null | undefined {
  if (value == null) return value as null | undefined;
  if (typeof value !== "object" || Array.isArray(value)) throw new Error(`${field} must be an object`);
  return value as Record<string, unknown>;
}

function count(value: unknown, field: string, min: number): number | undefined {
  if (value == null) return undefined;
  if (!Number.isInteger(value) || (value as number) < min) throw new Error(`${field} must be an integer of at least ${min}`);
  return value as number;
}

/** `events/poll` params as they arrive, checked. */
export function parsePollParams(raw: unknown): PollParams {
  const params = record(raw, "params") ?? {};
  if (typeof params.name !== "string" || params.name === "") throw new Error("name is required");
  if (params.cursor != null && typeof params.cursor !== "string") throw new Error("cursor must be a string or null");
  return {
    name: params.name,
    arguments: record(params.arguments, "arguments"),
    cursor: params.cursor as string | null | undefined,
    maxEvents: count(params.maxEvents, "maxEvents", 1),
    maxAgeMs: count(params.maxAgeMs, "maxAgeMs", 0),
  };
}
