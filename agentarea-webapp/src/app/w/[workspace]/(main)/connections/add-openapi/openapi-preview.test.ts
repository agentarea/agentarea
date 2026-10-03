import { describe, expect, it } from "vitest";
import { isAbsoluteBaseUrl, previewFromOpenAPISpec } from "./openapi-preview";

describe("OpenAPI preview URL handling", () => {
  const spec = {
    openapi: "3.0.3",
    info: { title: "Petstore" },
    servers: [{ url: "/api/v3" }],
    paths: { "/pets": { get: { operationId: "listPets" } } },
  };

  it("resolves a relative server URL against the loaded spec URL", () => {
    const preview = previewFromOpenAPISpec(
      spec,
      "https://petstore.example/openapi.json"
    );

    expect(preview.base_url).toBe("https://petstore.example/api/v3");
    expect(preview.tools).toEqual([
      { name: "listPets", description: "" },
    ]);
  });

  it("keeps pasted JSON server URLs relative and rejects them as base URLs", () => {
    const preview = previewFromOpenAPISpec(spec);

    expect(preview.base_url).toBe("/api/v3");
    expect(isAbsoluteBaseUrl(preview.base_url ?? "")).toBe(false);
    expect(isAbsoluteBaseUrl("https://api.example.com/v3")).toBe(true);
  });
});
