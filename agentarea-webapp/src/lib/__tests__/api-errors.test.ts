import { describe, expect, it } from "vitest";
import { apiErrorMessage, formatApiError } from "../api-errors";

describe("formatApiError", () => {
  it("reads a plain string detail", () => {
    expect(formatApiError({ detail: "Internal server error" })).toBe(
      "Internal server error"
    );
  });

  it("joins FastAPI validation detail arrays", () => {
    expect(
      formatApiError({ detail: [{ msg: "field required" }, { msg: "too long" }] })
    ).toBe("field required, too long");
  });

  it("reads the errors array out of a structured detail object", () => {
    // Shape raised whenever an endpoint passes a dict to HTTPException(detail=).
    // Before the detail-object branch existed this fell through to
    // JSON.stringify and the real message never reached the UI.
    const body = {
      detail: {
        message: "Import failed",
        errors: ["YAML validation error: env_vars must be a dictionary"],
        warnings: [],
      },
    };

    expect(formatApiError(body)).toBe(
      "YAML validation error: env_vars must be a dictionary"
    );
  });

  it("falls back to the structured detail's message when errors is empty", () => {
    expect(
      formatApiError({ detail: { message: "Import failed", errors: [] } })
    ).toBe("Import failed");
  });
});

describe("apiErrorMessage", () => {
  it("labels a structured import failure with its status", () => {
    const result = {
      status: 400,
      error: { detail: { message: "Import failed", errors: ["bad env_vars"] } },
    };

    expect(apiErrorMessage(result, "Failed to import workspace")).toBe(
      "Failed to import workspace (400): bad env_vars"
    );
  });

  it("omits an empty error body instead of printing {}", () => {
    expect(apiErrorMessage({ status: 500, error: {} }, "Failed")).toBe(
      "Failed (500)"
    );
  });
});
