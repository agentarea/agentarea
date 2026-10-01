import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";

// ProviderConfigCard and ProviderSpecCard: icon + subtitle + a models row.
function ProviderCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle lines={1} />;
}

interface ProvidersSkeletonProps {
  viewMode?: string;
  columns: SkeletonColumn[];
}

// Both models tabs: the same card grid, and a table with the tab's columns.
export default function ProvidersSkeleton({
  viewMode,
  columns,
}: ProvidersSkeletonProps) {
  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={columns}
      rows={5}
      gridClassName={CARD_GRID_DENSE}
      count={5}
      Card={ProviderCardSkeleton}
    />
  );
}
