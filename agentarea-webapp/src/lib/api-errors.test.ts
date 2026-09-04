import { describe, expect, it } from "vitest";
import { apiErrorMessage } from "./api-errors";

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
