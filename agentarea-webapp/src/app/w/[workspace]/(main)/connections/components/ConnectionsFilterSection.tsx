import {
  buildConnectionList,
  mcpConnectionListRow,
  openApiConnectionListRow,
  type ConnectionGroupBy,
  type ListFilter,
} from "../list-sections";
import { getConnectionsFrom } from "./connectionsData";
import ConnectionsFilter from "./ConnectionsFilter";

/**
 * Server wrapper that computes the per-filter counts (shared, request-cached
 * connections fetch) and renders the client-side filter tabs. The counts
 * describe the whole list, independent of the search.
 */
export default async function ConnectionsFilterSection({
  currentFilter,
  groupBy,
  source,
}: {
  currentFilter: ListFilter;
  groupBy: ConnectionGroupBy;
  source: string | null;
}) {
  const { instances, openApiConnections, usage } =
    await getConnectionsFrom(source);

  const { counts } = buildConnectionList(
    [
      ...instances.map((instance) =>
        mcpConnectionListRow(instance, usage[instance.id])
      ),
      ...openApiConnections.map(openApiConnectionListRow),
    ],
    "all"
  );

  return (
    <ConnectionsFilter
      currentFilter={currentFilter}
      counts={counts}
      groupedByState={groupBy === "state"}
    />
  );
}
