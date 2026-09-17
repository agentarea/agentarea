/**
 * Result shapes returned by an inbox task after the agent has finished.
 *
 * A response envelope may include validation and cost metadata alongside the
 * human-facing response. Those fields are intentionally not inferred into a
 * business outcome or rendered as part of the assistant message.
 */
export type InboxResultView =
  | { kind: "empty"; content: null }
  | { kind: "text"; content: string }
  | { kind: "structured"; content: string; value: object };

/** Return non-response envelope fields for an explicit, collapsed details view. */
export function getInboxResultDetails(result: unknown): object | null {
  if (result == null || typeof result !== "object" || Array.isArray(result)) {
    return null;
  }

  const details = Object.fromEntries(
    Object.entries(result).filter(([key]) => key !== "response")
  );
  return Object.keys(details).length > 0 ? details : null;
}

/**
 * Extract the assistant-facing result without exposing envelope metadata.
 * Unknown structured results remain available as a deliberately disclosed
 * JSON view so data is not silently discarded.
 */
export function extractInboxResult(result: unknown): InboxResultView {
  if (result == null || result === "") {
    return { kind: "empty", content: null };
  }

  if (typeof result === "string") {
    return { kind: "text", content: result };
  }

  if (typeof result !== "object") {
    return { kind: "text", content: String(result) };
  }

  if (Object.keys(result).length === 0) {
    return { kind: "empty", content: null };
  }

  if (
    "response" in result &&
    typeof (result as { response?: unknown }).response === "string"
  ) {
    const response = (result as { response: string }).response;
    return response
      ? { kind: "text", content: response }
      : { kind: "empty", content: null };
  }

  const content = JSON.stringify(result, null, 2);
  return {
    kind: "structured",
    content: content ?? String(result),
    value: result,
  };
}
