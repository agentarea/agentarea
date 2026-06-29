import CardGridSkeleton from "./CardGridSkeleton";
import TableSkeleton, { type SkeletonColumn } from "./TableSkeleton";

interface CollectionSkeletonProps {
  /**
   * The currently selected view (`"grid"` | `"table"`). It is known server-side
   * — read from the URL/cookie before the content suspends — so the placeholder
   * matches the view the user will actually see.
   */
  viewMode?: string;
  // --- table view ---
  columns: SkeletonColumn[];
  rows?: number;
  // --- grid view ---
  gridClassName: string;
  count?: number;
  Card: React.ComponentType;
}

/**
 * Single entry point for list-page loading placeholders. Switches between a
 * card-grid skeleton and a table skeleton based on `viewMode`, so the
 * placeholder always matches the user's selected view.
 */
export default function CollectionSkeleton({
  viewMode = "grid",
  columns,
  rows,
  gridClassName,
  count,
  Card,
}: CollectionSkeletonProps) {
  if (viewMode === "table") {
    return <TableSkeleton columns={columns} rows={rows} />;
  }

  return (
    <CardGridSkeleton count={count} className={gridClassName} Card={Card} />
  );
}
