import { describe, expect, it } from "vitest";
import { zWorkspaceRegistryCreate } from "@/api/client/zod.gen";
import {
  describeRegistrySource,
  emptyRegistryForm,
  mustMirror,
  toRegistryCreate,
  toRegistryUpdate,
} from "./registry-form";

describe("registry form", () => {
  it("sends a GitHub source with blanks as null and a valid body", () => {
    const body = toRegistryCreate({
      ...emptyRegistryForm(),
      name: "  acme skills ",
      source_url: " acme/skills ",
      source_ref: "main",
      source_path: "  ",
      credentials_secret_id: "",
    });

    expect(body).toMatchObject({
      name: "acme skills",
      source_type: "github",
      source_url: "acme/skills",
      source_ref: "main",
      source_path: null,
      description: null,
      credentials_secret_id: null,
    });
    expect(zWorkspaceRegistryCreate.safeParse(body).success).toBe(true);
  });

  it("drops a ref and path typed before switching to an index URL", () => {
    const body = toRegistryCreate({
      ...emptyRegistryForm(),
      name: "index",
      source_type: "url",
      source_url: "https://example.com/index.json",
      source_ref: "main",
      source_path: "skills",
    });

    expect(body.source_ref).toBeNull();
    expect(body.source_path).toBeNull();
  });

  it("clears the credentials on update with an explicit null", () => {
    const body = toRegistryUpdate({
      ...emptyRegistryForm(),
      name: "acme",
      source_url: "acme/skills",
      credentials_secret_id: "",
    });

    expect(body).toHaveProperty("credentials_secret_id", null);
    expect(body).not.toHaveProperty("source_type");
  });

  it("mirrors by default", () => {
    const body = toRegistryCreate({
      ...emptyRegistryForm(),
      name: "acme",
      source_url: "acme/skills",
    });
    expect(body.mode).toBe("mirror");
  });

  it("forces mirror on a skills registry read with credentials", () => {
    const form = {
      ...emptyRegistryForm(),
      name: "acme",
      source_url: "acme/skills",
      mode: "upstream" as const,
      credentials_secret_id: "0b6f8c1e-2a4d-4f7e-9a51-6d2c3b4a5e6f",
    };
    expect(mustMirror(form)).toBe(true);
    expect(toRegistryCreate(form).mode).toBe("mirror");
    expect(toRegistryUpdate(form).mode).toBe("mirror");
    expect(toRegistryCreate({ ...form, credentials_secret_id: "" }).mode).toBe(
      "upstream"
    );
    expect(toRegistryCreate({ ...form, registry_type: "agents" }).mode).toBe(
      "upstream"
    );
  });

  it("reads a repository source as owner/repo@ref:path", () => {
    expect(
      describeRegistrySource({
        source_type: "github",
        source_url: "acme/skills",
        source_ref: "v2",
        source_path: "skills",
      })
    ).toBe("acme/skills@v2:skills");
    expect(
      describeRegistrySource({
        source_type: "url",
        source_url: "https://example.com/index.json",
      })
    ).toBe("https://example.com/index.json");
  });
});
