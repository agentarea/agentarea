import { describe, expect, it } from "vitest";
import {
  credentialUpdateSpec,
  declaredCredentialFields,
  missingSecretFields,
  requiredSecretFields,
} from "./credential-fields";

describe("declaredCredentialFields", () => {
  it("reads a remote server's headers before its env schema", () => {
    const server = {
      env_schema: [{ name: "FROM_SCHEMA", isSecret: true }],
      json_spec: { remotes: [{ headers: [{ name: "Authorization", isSecret: true }] }] },
    };
    expect(declaredCredentialFields(server, "url").map((f) => f.name)).toEqual([
      "Authorization",
    ]);
    expect(declaredCredentialFields(server, "docker").map((f) => f.name)).toEqual([
      "FROM_SCHEMA",
    ]);
  });
});

describe("requiredSecretFields", () => {
  it("counts a secret as required only when the schema says so, like the API", () => {
    // The API's normalizer reads isRequired, then required, and defaults to
    // false: an unmarked secret is optional.
    const declared = declaredCredentialFields(
      {
        env_schema: [
          { name: "MARKED", isSecret: true, isRequired: true },
          { name: "LEGACY", isSecret: true, required: true },
          { name: "UNMARKED", isSecret: true },
          { name: "OVERRIDDEN", isSecret: true, isRequired: false, required: true },
          { name: "PLAIN", isRequired: true },
        ],
      },
      "docker"
    );
    expect(requiredSecretFields(declared).map((f) => f.name)).toEqual([
      "MARKED",
      "LEGACY",
    ]);
  });
});

describe("missingSecretFields", () => {
  const fields = [
    { name: "STORED", isSecret: true, isRequired: true },
    { name: "TYPED", isSecret: true, isRequired: true },
    { name: "EMPTY", isSecret: true, isRequired: true },
    { name: "OPTIONAL", isSecret: true, isRequired: false },
    { name: "UNMARKED", isSecret: true },
    { name: "PLAIN", isRequired: true },
  ];

  it("keeps only required secrets with no stored or typed value", () => {
    // A stored secret's value never comes back: only its name in env_vars.
    const spec = {
      env_vars: ["STORED"],
      headers: { TYPED: "abc", EMPTY: "  " },
    };
    expect(missingSecretFields(fields, spec).map((f) => f.name)).toEqual(["EMPTY"]);
  });
});

describe("credentialUpdateSpec", () => {
  it("keeps the rest of the spec and drops the fields the API rejects", () => {
    // An update replaces json_spec, so env_vars and other headers must ride
    // along; transport fields are refused and restored by the API.
    const spec = {
      type: "url",
      endpoint_url: "https://mcp.example.com",
      env_vars: ["OLD"],
      headers: { OLD: "******", "X-Team": "core" },
    };
    expect(credentialUpdateSpec(spec, "url", { NEW: " key ", BLANK: "" })).toEqual({
      env_vars: ["OLD"],
      headers: { OLD: "******", "X-Team": "core", NEW: "key" },
    });
  });

  it("writes a container's values into its environment", () => {
    expect(credentialUpdateSpec({}, "docker", { TOKEN: "t" })).toEqual({
      environment: { TOKEN: "t" },
    });
  });
});
