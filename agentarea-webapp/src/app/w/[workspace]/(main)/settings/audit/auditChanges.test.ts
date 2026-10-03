import { describe, expect, it } from "vitest";
import { auditChangeLines, MASKED } from "./auditChanges";
import { auditEventsToCsv } from "./auditCsv";

describe("auditChangeLines", () => {
  it("spells out which keys of an object changed instead of [object Object]", () => {
    const lines = auditChangeLines([
      {
        field: "json_spec",
        before: { endpoint_url: "https://a.example", timeout: 30 },
        after: { endpoint_url: "https://b.example", timeout: 30 },
      },
    ]);

    expect(lines).toEqual([
      {
        field: "json_spec.endpoint_url",
        before: "https://a.example",
        after: "https://b.example",
      },
    ]);
  });

  it("masks every value under headers and env, keeping which key changed", () => {
    const lines = auditChangeLines([
      {
        field: "headers",
        before: { "X-Team": "red" },
        after: { "X-Team": "blue", "X-Region": "eu" },
      },
      { field: "json_spec", before: { env: {} }, after: { env: { DB_URL: "pg://u:p@h" } } },
    ]);

    expect(lines).toEqual([
      { field: "headers.X-Region", before: "null", after: MASKED },
      { field: "headers.X-Team", before: MASKED, after: MASKED },
      { field: "json_spec.env.DB_URL", before: "null", after: MASKED },
    ]);
    expect(JSON.stringify(lines)).not.toMatch(/pg:\/\/|red|blue|eu/);
  });

  it("masks a credential-named key wherever it sits", () => {
    const [line] = auditChangeLines([
      { field: "settings", before: { apiToken: "old" }, after: { apiToken: "new" } },
    ]);

    expect(line).toEqual({ field: "settings.apiToken", before: MASKED, after: MASKED });
  });

  it("keeps scalar diffs as they are and skips values that did not change", () => {
    expect(
      auditChangeLines([
        { field: "name", before: "old", after: "new" },
        { field: "tags", before: ["a"], after: ["a"] },
      ])
    ).toEqual([{ field: "name", before: "old", after: "new" }]);
  });
});

describe("auditEventsToCsv", () => {
  const event = {
    id: "e1",
    created_at: "2026-10-03T10:00:00Z",
    actor_id: "user-1",
    actor_type: "user",
    workspace_id: "ws",
    source_ip: null,
    user_agent: null,
    request_id: null,
    action: "secret.update",
    resource_type: "secret",
    resource_id: "s1",
    changes: [{ field: "description", before: null, after: 'say "hi", ok' }],
    event_metadata: { resource_name: "=HYPERLINK(1)" },
  };

  it("writes a header row and quotes cells holding separators", () => {
    const [header, row] = auditEventsToCsv([event]).trimEnd().split("\r\n");

    expect(header).toBe(
      "created_at,action,actor_type,actor_id,resource_type,resource_id,source_ip,details,changes"
    );
    expect(row).toContain('"description: null -> say ""hi"", ok"');
  });

  it("neutralises a cell a spreadsheet would run as a formula", () => {
    const csv = auditEventsToCsv([
      { ...event, resource_id: "=cmd|' /C calc'!A0", changes: null },
    ]);

    expect(csv).toContain(",'=cmd|' /C calc'!A0,");
  });
});
