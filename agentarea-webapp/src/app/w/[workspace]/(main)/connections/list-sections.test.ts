import { describe, expect, it } from "vitest";
import { buildConnectionList, type ConnectionListRow } from "./list-sections";
import type { ConnectionStateKey } from "./state";
import type { ConnectionUsage } from "./usage";

function row(
  name: string,
  key: ConnectionStateKey,
  usage?: ConnectionUsage,
  type: ConnectionListRow["_type"] = "mcp"
): ConnectionListRow {
  return {
    name,
    _type: type,
    _state: { key, kind: "draft", at: null },
    _usage: usage,
  };
}

const rows = [
  row("slack", "ready", { agents: 0, grantedTools: 6 }),
  row("github", "working", { agents: 3, grantedTools: 12 }),
  row("stripe", "failing", { agents: 1, grantedTools: null }),
];

const names = (list: ConnectionListRow[]) => list.map((r) => r.name);

describe("buildConnectionList", () => {
  it("puts the section that needs attention above the working ones", () => {
    const { sections, showSectionHeadings } = buildConnectionList(rows, "all");

    expect(sections.map((s) => [s.key, names(s.rows)])).toEqual([
      ["attention", ["stripe"]],
      ["active", ["github"]],
      ["idle", ["slack"]],
    ]);
    expect(showSectionHeadings).toBe(true);
  });

  it("sorts the worse verdict first within a section, then by name", () => {
    const { sections } = buildConnectionList(
      [
        row("b-unset", "unconfigured"),
        row("a-unset", "unconfigured"),
        row("broken", "broken"),
        row("z-failing", "failing"),
        row("probe", "verifying"),
        row("works", "working"),
      ],
      "all"
    );

    expect(names(sections[0].rows)).toEqual([
      "z-failing",
      "broken",
      "a-unset",
      "b-unset",
    ]);
    expect(names(sections[1].rows)).toEqual(["works", "probe"]);
  });

  it("counts unused and unrestricted connections for the filter chips", () => {
    const { counts } = buildConnectionList(
      [...rows, row("petstore", "ready")],
      "all"
    );

    // A row with no usage record (OpenAPI) is neither unused nor unrestricted.
    expect(counts).toEqual({
      all: 4,
      attention: 1,
      unused: 1,
      unrestricted: 1,
    });
  });

  it("keeps the counts of the whole list while a filter narrows it", () => {
    const { counts, visibleRows } = buildConnectionList(rows, "attention");

    expect(names(visibleRows)).toEqual(["stripe"]);
    expect(counts.all).toBe(3);
  });

  it("narrows to unused connections and drops headings for a single bucket", () => {
    const { visibleRows, sections, showSectionHeadings } = buildConnectionList(
      rows,
      "unused"
    );

    expect(names(visibleRows)).toEqual(["slack"]);
    expect(sections.map((s) => s.key)).toEqual(["idle"]);
    expect(showSectionHeadings).toBe(false);
  });

  it("narrows to connections some agent holds with every tool", () => {
    expect(
      names(buildConnectionList(rows, "unrestricted").visibleRows)
    ).toEqual(["stripe"]);
  });

  it("hides headings when every connection lands in one section", () => {
    const { sections, showSectionHeadings } = buildConnectionList(
      [row("github", "working"), row("linear", "verifying")],
      "all"
    );

    expect(sections).toHaveLength(1);
    expect(showSectionHeadings).toBe(false);
  });

  it("groups by protocol, MCP first, worst verdict on top", () => {
    const { sections } = buildConnectionList(
      [
        row("petstore", "ready", undefined, "openapi"),
        ...rows,
        row("billing", "broken", undefined, "openapi"),
      ],
      "all",
      "type"
    );

    expect(sections.map((s) => [s.key, names(s.rows)])).toEqual([
      ["mcp", ["stripe", "github", "slack"]],
      ["openapi", ["billing", "petstore"]],
    ]);
  });

  it("keeps one ordered list when grouping is off", () => {
    const { sections, showSectionHeadings } = buildConnectionList(
      rows,
      "all",
      "none"
    );

    expect(sections.map((s) => [s.key, names(s.rows)])).toEqual([
      ["all", ["stripe", "github", "slack"]],
    ]);
    expect(showSectionHeadings).toBe(false);
  });
});
