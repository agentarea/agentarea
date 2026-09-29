import { useMemo, useState } from "react";
import {
  buildPrincipalLookup,
  countToolFacets,
  filterTools,
  groupToolsByName,
  groupToolsByPath,
  toToolRows,
  type Tool,
  type ToolFacet,
  type ToolsTableConsumer,
} from "./tool-facets";

export function useToolFacets(
  tools: Tool[],
  consumers: ToolsTableConsumer[] | null | undefined
) {
  const [query, setQuery] = useState("");
  const [facet, setFacet] = useState<ToolFacet>("all");

  const principalsFor = useMemo(
    () => buildPrincipalLookup(consumers),
    [consumers]
  );

  // OpenAPI tools carry method/path and group naturally by path prefix.
  // MCP tools have neither, so they get search, facets and name-prefix groups.
  const isOpenAPI = tools.some((tool) => !!tool.path);
  const hasDestructive = tools.some(
    (tool) => tool.annotations?.destructiveHint
  );
  const hasReadOnly = tools.some((tool) => tool.annotations?.readOnlyHint);
  const searching = query.trim().length > 0;

  const filtered = useMemo(
    () => filterTools(tools, { query, facet, principalsFor }),
    [tools, query, facet, principalsFor]
  );

  // Counts make the toolbar answer "how many destructive tools does this
  // server even expose" without clicking each chip.
  const facetCounts = useMemo(
    () => countToolFacets(tools, principalsFor),
    [tools, principalsFor]
  );

  const mcpRows = useMemo(
    () => (isOpenAPI ? [] : toToolRows(filtered)),
    [filtered, isOpenAPI]
  );

  const mcpGroups = useMemo(
    () =>
      isOpenAPI ? [] : groupToolsByName(mcpRows, { principalsFor, searching }),
    [isOpenAPI, searching, mcpRows, principalsFor]
  );

  const pathGroups = useMemo(
    () => (isOpenAPI ? groupToolsByPath(filtered) : []),
    [filtered, isOpenAPI]
  );

  return {
    query,
    setQuery,
    facet,
    setFacet,
    principalsFor,
    isOpenAPI,
    hasDestructive,
    hasReadOnly,
    searching,
    filtered,
    facetCounts,
    mcpRows,
    mcpGroups,
    pathGroups,
  };
}
