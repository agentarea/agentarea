import { CollectionSkeleton, type SkeletonColumn } from "@/components/Skeleton";
import { AGENTS_GRID_CLASS } from "./agentColumns";
import AgentCardSkeleton from "./AgentCardSkeleton";

interface AgentsSkeletonProps {
  /** Selected view, known server-side (URL/cookie) before content suspends. */
  viewMode?: string;
  /** Resolved table columns (header labels need translations from the page). */
  columns: SkeletonColumn[];
}

/**
 * Loading placeholder for the agents list — switches between the grid of
 * `AgentCardSkeleton`s and a `TableSkeleton`, matching the selected view.
 */
export default function AgentsSkeleton({
  viewMode,
  columns,
}: AgentsSkeletonProps) {
  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={columns}
      rows={8}
      gridClassName={AGENTS_GRID_CLASS}
      count={10}
      Card={AgentCardSkeleton}
    />
  );
}
