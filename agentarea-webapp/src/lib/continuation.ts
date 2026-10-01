import type { ContinueTaskPayload } from "@/api/client/types.gen";
import {
  canonicalType,
  TASK_AWAITING_CONTINUATION,
} from "@/lib/events/contract";
import type { TimelineItem } from "@/lib/events/reducer";

export type ContinuationField =
  | "iterations"
  | "budget"
  | "tokens"
  | "toolCalls";

export type ContinuationForm = Record<ContinuationField, string>;

export type ContinuationGrantError =
  | "invalid"
  | "grant_required"
  | "iterations_required"
  | "budget_required"
  | "tokens_required"
  | "toolCalls_required";

export type ContinuationGrantResult =
  | { ok: true; payload: ContinueTaskPayload }
  | { ok: false; error: ContinuationGrantError };

const LIMIT_FIELD: Record<string, ContinuationField> = {
  iteration_limit: "iterations",
  budget_exceeded: "budget",
  token_limit: "tokens",
  tool_call_limit: "toolCalls",
};

const COUNT_MAX: Record<Exclude<ContinuationField, "budget">, number> = {
  iterations: 1000,
  tokens: 10_000_000,
  toolCalls: 10_000,
};

const DEFAULT_GRANT: ContinuationForm = {
  iterations: "10",
  budget: "",
  tokens: "100000",
  toolCalls: "50",
};

const BASE_FIELDS: ContinuationField[] = ["iterations", "budget"];

/** The failure_reason of the most recent task.awaiting_continuation, else null. */
export function latestContinuationReason(
  timeline: readonly TimelineItem[]
): string | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const item = timeline[index];
    if (canonicalType(item.eventType) !== TASK_AWAITING_CONTINUATION) continue;
    const reason = (item.data as Record<string, unknown>).failure_reason;
    return typeof reason === "string" ? reason : null;
  }
  return null;
}

/** The limit a continuation must lift for this failure reason, if known. */
export function limitField(reason: string | null): ContinuationField | null {
  return (reason && LIMIT_FIELD[reason]) || null;
}

/**
 * Grant inputs to show: the exhausted limit first, then iterations and budget.
 * An unknown reason shows every grant the API accepts.
 */
export function continuationFields(reason: string | null): ContinuationField[] {
  const limit = limitField(reason);
  if (limit === null) {
    return [...BASE_FIELDS, "tokens", "toolCalls"];
  }
  return [limit, ...BASE_FIELDS.filter((field) => field !== limit)];
}

/** Pre-fill only the exhausted limit; an unknown reason keeps the iteration default. */
export function defaultContinuationForm(
  reason: string | null
): ContinuationForm {
  const limit = limitField(reason) ?? "iterations";
  return {
    iterations: "",
    budget: "",
    tokens: "",
    toolCalls: "",
    [limit]: DEFAULT_GRANT[limit],
  };
}

function parseCount(value: string, max: number): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return 0;
  if (!/^\d+$/.test(trimmed)) return null;
  const count = Number(trimmed);
  return count <= max ? count : null;
}

function parseBudget(value: string): string | undefined | null {
  const trimmed = value.trim();
  if (trimmed === "") return undefined;
  if (!/^\d+(\.\d+)?$/.test(trimmed) || Number(trimmed) <= 0) return null;
  return trimmed;
}

/** Validate the visible grant inputs into a continue request body. */
export function parseContinuationGrant(
  form: ContinuationForm,
  reason: string | null
): ContinuationGrantResult {
  const visible = new Set(continuationFields(reason));
  const count = (field: Exclude<ContinuationField, "budget">) =>
    visible.has(field) ? parseCount(form[field], COUNT_MAX[field]) : 0;

  const iterations = count("iterations");
  const tokens = count("tokens");
  const toolCalls = count("toolCalls");
  const budget = visible.has("budget") ? parseBudget(form.budget) : undefined;
  if (
    iterations === null ||
    tokens === null ||
    toolCalls === null ||
    budget === null
  ) {
    return { ok: false, error: "invalid" };
  }

  const granted: Record<ContinuationField, boolean> = {
    iterations: iterations > 0,
    budget: budget !== undefined,
    tokens: tokens > 0,
    toolCalls: toolCalls > 0,
  };
  const limit = limitField(reason);
  if (limit !== null && !granted[limit]) {
    return { ok: false, error: `${limit}_required` };
  }
  if (!Object.values(granted).some(Boolean)) {
    return { ok: false, error: "grant_required" };
  }

  const payload: ContinueTaskPayload = {
    additional_iterations: iterations,
    additional_tokens: tokens,
    additional_tool_calls: toolCalls,
  };
  if (budget !== undefined) payload.additional_budget_usd = budget;
  return { ok: true, payload };
}
