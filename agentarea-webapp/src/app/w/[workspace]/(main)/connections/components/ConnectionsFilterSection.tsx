import {
  buildConnectionList,
  mcpConnectionListRow,
  openApiConnectionListRow,
  type ListFilter,
} from "../list-sections";
import ConnectionsFilter from "./ConnectionsFilter";
import { getConnectionsCached } from "./connectionsData";

/**
 * Server wrapper that computes the per-filter counts (shared, request-cached
 * connections fetch) and renders the client-side filter tabs. The counts
 * describe the whole list, independent of the search.
 */
export default async function ConnectionsFilterSection({
  currentFilter,
}: {
  currentFilter: ListFilter;
}) {
  const { instances, openApiConnections, usage } = await getConnectionsCached();

  const { counts } = buildConnectionList(
    [
      ...instances.map((instance) =>
        mcpConnectionListRow(instance, usage[instance.id])
      ),
      ...openApiConnections.map(openApiConnectionListRow),
    ],
    "all"
  );

  return <ConnectionsFilter currentFilter={currentFilter} counts={counts} />;
}
