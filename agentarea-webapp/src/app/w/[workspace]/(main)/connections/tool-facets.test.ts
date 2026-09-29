import { describe, expect, it } from "vitest";
import {
  buildPrincipalLookup,
  countToolFacets,
  filterTools,
  groupToolsByName,
  groupToolsByPath,
  OTHER_GROUP_KEY,
  toToolRows,
  type Tool,
  type ToolsTableConsumer,
} from "./tool-facets";

// A server wide enough to trigger grouping: 10 issue tools, 10 repo tools,
// 8 pull tools — verb-first names, the flat convention real MCP servers use.
function wideServer(): Tool[] {
  const tools: Tool[] = [];
  for (let i = 0; i < 10; i++) {
    tools.push({ name: `list_issues_${i}`, description: `issue tool ${i}` });
  }
  for (let i = 0; i < 10; i++) {
    tools.push({ name: `get_repos_${i}`, description: `repo tool ${i}` });
  }
  for (let i = 0; i < 8; i++) {
    tools.push({ name: `create_pulls_${i}`, description: `pull tool ${i}` });
  }
  return tools;
}

const annotated: Tool[] = [
  {
    name: "delete_repo",
    description: "removes a repository",
    annotations: { destructiveHint: true },
  },
  {
    name: "read_file",
    title: "Read a file",
    description: "reads a file",
    annotations: { readOnlyHint: true },
  },
  { name: "open_pr", description: "opens a pull request" },
];

const reader: ToolsTableConsumer = {
  agent_id: "agent-1",
  agent_name: "Reader Agent",
  enabled_tools: ["read_file"],
  confirm_tools: [],
};

describe("buildPrincipalLookup", () => {
  it("has no answer when consumer data is absent", () => {
    expect(buildPrincipalLookup(undefined)).toBeNull();
    expect(buildPrincipalLookup(null)).toBeNull();
  });

  it("counts an all-tools agent as a principal of every tool", () => {
    const principalsFor = buildPrincipalLookup([
      {
        agent_id: "agent-1",
        agent_name: "Wildcard Agent",
        enabled_tools: null,
        confirm_tools: ["delete_repo"],
      },
    ]);

    expect(principalsFor?.("delete_repo")).toEqual([
      {
        agentId: "agent-1",
        name: "Wildcard Agent",
        slug: undefined,
        needsConfirm: true,
        viaAllTools: true,
      },
    ]);
    expect(principalsFor?.("read_file")[0].needsConfirm).toBe(false);
  });

  it("reports a tool no agent equipped as having no principals", () => {
    const principalsFor = buildPrincipalLookup([reader]);

    expect(principalsFor?.("delete_repo")).toEqual([]);
    expect(principalsFor?.("read_file").map((p) => p.name)).toEqual([
      "Reader Agent",
    ]);
  });
});

describe("countToolFacets", () => {
  it("counts each facet across the whole tool list", () => {
    expect(countToolFacets(annotated, buildPrincipalLookup([reader]))).toEqual({
      all: 3,
      equipped: 1,
      unequipped: 2,
      destructive: 1,
      readOnly: 1,
    });
  });

  it("counts nothing as equipped without consumer data", () => {
    const counts = countToolFacets(annotated, null);

    expect(counts.equipped).toBe(0);
    expect(counts.unequipped).toBe(3);
  });
});

describe("filterTools", () => {
  const principalsFor = buildPrincipalLookup([reader]);
  const names = (tools: Tool[]) => tools.map((tool) => tool.name);

  it("narrows by the server's safety hints", () => {
    expect(
      names(
        filterTools(annotated, {
          query: "",
          facet: "destructive",
          principalsFor,
        })
      )
    ).toEqual(["delete_repo"]);
    expect(
      names(
        filterTools(annotated, { query: "", facet: "readOnly", principalsFor })
      )
    ).toEqual(["read_file"]);
  });

  it("splits equipped from unequipped tools", () => {
    expect(
      names(
        filterTools(annotated, { query: "", facet: "equipped", principalsFor })
      )
    ).toEqual(["read_file"]);
    expect(
      names(
        filterTools(annotated, {
          query: "",
          facet: "unequipped",
          principalsFor,
        })
      )
    ).toEqual(["delete_repo", "open_pr"]);
  });

  it("lets equipment facets through when consumer data is absent", () => {
    expect(
      filterTools(annotated, {
        query: "",
        facet: "equipped",
        principalsFor: null,
      })
    ).toHaveLength(3);
  });

  it("searches name, title and description, ignoring case and padding", () => {
    const search = (query: string) =>
      names(filterTools(annotated, { query, facet: "all", principalsFor }));

    expect(search("  DELETE_ ")).toEqual(["delete_repo"]);
    expect(search("read a file")).toEqual(["read_file"]);
    expect(search("pull request")).toEqual(["open_pr"]);
  });
});

describe("toToolRows", () => {
  it("orders by description, falling back to the name", () => {
    const rows = toToolRows([
      { name: "zeta", description: "" },
      { name: "b_tool", description: "Alpha" },
      { name: "a_tool", description: "beta" },
    ]);

    expect(rows.map((row) => row.name)).toEqual(["b_tool", "a_tool", "zeta"]);
  });
});

describe("groupToolsByName", () => {
  const group = (
    tools: Tool[],
    options: Partial<Parameters<typeof groupToolsByName>[1]> = {}
  ) =>
    groupToolsByName(toToolRows(tools), {
      principalsFor: null,
      searching: false,
      ...options,
    });

  it("keeps a server at or under the threshold as a flat list", () => {
    expect(group(wideServer().slice(0, 24))).toEqual([]);
  });

  it("bypasses grouping while searching", () => {
    expect(group(wideServer(), { searching: true })).toEqual([]);
  });

  it("buckets verb-first names by their object, largest first", () => {
    const groups = group(wideServer());

    expect(groups.map((g) => [g.key, g.rows.length])).toEqual([
      ["issue", 10],
      ["repo", 10],
      ["pull", 8],
    ]);
  });

  it("opens only the first group when nothing is explicitly granted", () => {
    const groups = group(wideServer());

    expect(groups.map((g) => g.open)).toEqual([true, false, false]);
  });

  it("opens the group holding equipped tools instead of the largest one", () => {
    const groups = group(wideServer(), {
      principalsFor: buildPrincipalLookup([
        {
          agent_id: "agent-1",
          agent_name: "Ops Agent",
          enabled_tools: ["get_repos_3"],
          confirm_tools: ["get_repos_3"],
        },
      ]),
    });

    expect(groups.filter((g) => g.open).map((g) => g.key)).toEqual(["repo"]);
  });

  it("ignores an all-tools grant when choosing which groups to open", () => {
    const groups = group(wideServer(), {
      principalsFor: buildPrincipalLookup([
        { agent_id: "a", agent_name: "Wildcard", enabled_tools: null },
      ]),
    });

    expect(groups.map((g) => g.open)).toEqual([true, false, false]);
  });

  it("groups namespaced tools by namespace and sweeps singletons into other", () => {
    const tools: Tool[] = [
      ...Array.from({ length: 23 }, (_, i) => ({
        name: `github__tool_${i}`,
        description: "",
      })),
      { name: "zendesk_ticket", description: "" },
      { name: "archive", description: "" },
    ];

    const groups = group(tools);

    expect(groups.map((g) => g.key)).toEqual(["github", OTHER_GROUP_KEY]);
    expect(groups[1].rows.map((row) => row.name)).toEqual([
      "archive",
      "zendesk_ticket",
    ]);
  });
});

describe("groupToolsByPath", () => {
  it("groups OpenAPI operations by the first non-version path segment", () => {
    const groups = groupToolsByPath([
      {
        name: "listPayments",
        description: "List payments",
        method: "GET",
        path: "/acquiring/v1.0/payments",
      },
      {
        name: "getAccounts",
        description: "Get accounts",
        method: "GET",
        path: "/open-banking/v1.0/accounts",
      },
      {
        name: "createPayment",
        description: "Create payment",
        method: "POST",
        path: "/acquiring/v1.0/payments",
      },
    ]);

    expect(groups.map((g) => [g.key, g.rows.map((row) => row.name)])).toEqual([
      ["acquiring", ["createPayment", "listPayments"]],
      ["open-banking", ["getAccounts"]],
    ]);
  });
});
