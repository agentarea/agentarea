import { describe, expect, it } from "vitest";
import {
  apiErrorMessage,
  catalogFetchFailure,
  unreachableApiResponse,
} from "./api-errors";

/**
 * The generated client hands back the parsed error *body*, not a string.
 * Anything that interpolates it directly — `String(error)`, `error.toString()` —
 * renders "[object Object]" in the UI and buries the only clue about what
 * actually failed.
 */
describe("apiErrorMessage", () => {
  it("unwraps a FastAPI detail instead of stringifying the object", () => {
    const message = apiErrorMessage(
      { error: { detail: "Agent not found" }, status: 404 },
      "Failed to load events"
    );

    expect(message).toBe("Failed to load events (404): Agent not found");
    expect(message).not.toContain("[object Object]");
  });

  it("unwraps problem+json validation errors", () => {
    const message = apiErrorMessage(
      {
        error: { errors: [{ msg: "page_size must be <= 100" }] },
        status: 422,
      },
      "Failed to load events"
    );

    expect(message).toBe(
      "Failed to load events (422): page_size must be <= 100"
    );
  });

  it("never emits [object Object] for a validation item with no msg field", () => {
    const message = apiErrorMessage(
      { error: { errors: [{ field: "page_size", reason: "too large" }] }, status: 422 },
      "Failed"
    );

    expect(message).not.toContain("[object Object]");
    expect(message).toContain("page_size");
    expect(message).toContain("too large");
  });

  it("keeps the status when the body carries no readable message", () => {
    const message = apiErrorMessage({ error: {}, status: 500 }, "Failed");

    expect(message).toBe("Failed (500)");
  });

  it("falls back to the label alone when there is no error and no status", () => {
    expect(apiErrorMessage({ data: null }, "Failed to load events")).toBe(
      "Failed to load events"
    );
  });

  it("passes a plain string error through", () => {
    expect(apiErrorMessage({ error: "boom" }, "Failed")).toBe("Failed: boom");
  });
});

describe("catalogFetchFailure", () => {
  const problem = (status: number, code: string) => ({
    error: { status, code, detail: "server words" },
    status,
  });

  it("tells the 409s apart by their problem code", () => {
    expect(catalogFetchFailure(problem(409, "skill_customized"))).toBe(
      "customized"
    );
    expect(catalogFetchFailure(problem(409, "skill_not_from_catalog"))).toBe(
      "notFromCatalog"
    );
    expect(catalogFetchFailure(problem(409, "skill_tree_mismatch"))).toBe(
      "moved"
    );
  });

  it("names the source failures", () => {
    expect(catalogFetchFailure(problem(410, "skill_source_gone"))).toBe(
      "removedUpstream"
    );
    expect(catalogFetchFailure(problem(429, "github_rate_limited"))).toBe(
      "rateLimited"
    );
    expect(catalogFetchFailure(problem(502, "skill_source_unreachable"))).toBe(
      "sourceUnreachable"
    );
  });

  it("reads a 403 as the install policy refusing", () => {
    expect(catalogFetchFailure(problem(403, "permission_denied"))).toBe(
      "refusedByPolicy"
    );
  });

  it("leaves a status without a known code to the generic message", () => {
    expect(catalogFetchFailure({ error: { detail: "x" }, status: 409 })).toBeNull();
    expect(catalogFetchFailure(problem(500, "internal_error"))).toBeNull();
    expect(catalogFetchFailure({ error: "offline" })).toBeNull();
  });
});

/**
 * A server action that hands an `Error` to the browser loses its message in a
 * production build: React replaces it with "Minified React error #441". A
 * request the API never answered must reach the caller as an ordinary error
 * body instead.
 */
describe("unreachableApiResponse", () => {
  it("reports a timed-out request as a 504 that names the budget", async () => {
    const response = unreachableApiResponse(
      new DOMException("The operation was aborted due to timeout", "TimeoutError"),
      8000
    );

    expect(response?.status).toBe(504);
    const result = { error: await response?.json(), status: response?.status };
    expect(apiErrorMessage(result, "Failed to load agents")).toBe(
      "Failed to load agents (504): The API did not answer within 8 s"
    );
  });

  it("reports a failed connection as a 502 with its error code", async () => {
    const error = new TypeError("fetch failed", {
      cause: Object.assign(new Error("connect ECONNREFUSED 10.0.0.7:8000"), {
        code: "ECONNREFUSED",
      }),
    });

    const response = unreachableApiResponse(error, 8000);

    expect(response?.status).toBe(502);
    expect(await response?.json()).toEqual({
      detail: "The API could not be reached (ECONNREFUSED)",
    });
  });

  it("leaves a request its caller aborted alone", () => {
    expect(
      unreachableApiResponse(new DOMException("aborted", "AbortError"), 8000)
    ).toBeNull();
  });
});
