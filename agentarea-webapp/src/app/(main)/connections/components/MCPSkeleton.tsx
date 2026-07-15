import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";

// MCPInstanceCard / OpenAPIConnectionCard: icon + status/type subtitle, no body.
function MCPCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle />;
}

/** Skeleton columns matching the unified connections table (Type + 5 cols). */
export function mcpSkeletonColumns(t: (key: string) => string): SkeletonColumn[] {
  return [
    { header: "Type", barClassName: "h-5 w-16 rounded-full" },
    { header: t("table.name"), barClassName: "h-4 w-40" },
    { header: t("table.description"), barClassName: "h-3 w-48" },
    { header: t("table.endpoint"), barClassName: "h-3 w-32" },
    { header: "Tools", barClassName: "h-4 w-8" },
    { header: t("table.status"), barClassName: "h-5 w-20 rounded-full" },
  ];
}

interface MCPSkeletonProps {
  viewMode?: string;
  columns: SkeletonColumn[];
  /** "My connections" section heading — kept visible while content loads. */
  headerLabel: string;
}

export default function MCPSkeleton({
  viewMode,
  columns,
  headerLabel,
}: MCPSkeletonProps) {
  return (
    <div className="py-1">
      <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
        {headerLabel}
      </h4>
      <CollectionSkeleton
        viewMode={viewMode}
        columns={columns}
        rows={8}
        gridClassName={CARD_GRID_DENSE}
        count={10}
        Card={MCPCardSkeleton}
      />
    </div>
  );
}
