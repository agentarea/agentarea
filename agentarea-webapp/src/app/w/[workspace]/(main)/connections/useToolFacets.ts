import { useMemo, useState } from "react";
import {
  buildPrincipalLookup,
  countToolFacets,
  filterTools,
  groupToolsByName,
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

  // MCP and OpenAPI tools alike: name-ordered rows, name-prefix groups once
  // a server is wide enough to need them.
  const rows = useMemo(() => toToolRows(filtered), [filtered]);

  const groups = useMemo(
    () => groupToolsByName(rows, { principalsFor, searching }),
    [searching, rows, principalsFor]
  );

  return {
    query,
    setQuery,
    facet,
    setFacet,
    principalsFor,
    hasDestructive,
    hasReadOnly,
    searching,
    filtered,
    facetCounts,
    rows,
    groups,
  };
}
