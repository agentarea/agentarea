/**
 * SSE payload normalization for the canonical event contract.
 *
 * The backend wraps rich event content under original_data / data; this flattens
 * an SSE envelope into a { eventType, data } EventInput the reducer understands.
 * Shared by the useTaskEvents hook and the create-and-stream chat surface.
 */

import { EventInput } from "./contract";

type RawData = Record<string, unknown>;

function asRecord(value: unknown): RawData {
  return value && typeof value === "object" ? (value as RawData) : {};
}

/** Flatten an SSE payload into { eventType, data }, or null when unusable. */
export function normalizeSSEEvent(type: string, raw: unknown): EventInput | null {
  const payload = asRecord(raw);
  const eventType =
    (typeof payload.original_event_type === "string" &&
      payload.original_event_type) ||
    (typeof payload.event_type === "string" && payload.event_type) ||
    type;
  if (!eventType) return null;

  const inner = asRecord(payload.data);
  const original = asRecord(payload.original_data);
  const data: RawData = { ...payload, ...inner, ...original };
  delete data.original_data;
  delete data.original_event_type;

  return { eventType, data };
}

/**
 * Map a persisted history event into a contract EventInput.
 *
 * The row's `id` is the same value the live envelope carries as `event_id`, so
 * it has to travel with the payload: it is what lets the SSE catch-up replay
 * dedup against history instead of folding every row a second time. The row's
 * `timestamp` travels too — metadata never carries one. The row `message` does
 * not: it is `metadata.message` read back, so it adds nothing to the payload.
 */
export function normalizeHistory(event: {
  id?: string;
  event_type: string;
  timestamp: string;
  metadata?: Record<string, unknown> | null;
}): EventInput {
  const meta = asRecord(event.metadata);
  const original = asRecord(meta.original_data);
  const data: RawData = { ...meta, ...original };
  delete data.original_data;
  data.timestamp = event.timestamp;
  if (event.id && data.event_id === undefined) data.event_id = event.id;
  return { eventType: event.event_type, data };
}

/** When the event happened, or null when it carries no usable timestamp. */
export function eventTimestamp(data: RawData): Date | null {
  const raw =
    (typeof data.timestamp === "string" && data.timestamp) ||
    (typeof data.original_timestamp === "string" && data.original_timestamp) ||
    null;
  if (!raw) return null;
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? null : date;
}
