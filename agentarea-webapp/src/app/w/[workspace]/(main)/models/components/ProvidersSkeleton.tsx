import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";

// ProviderConfigCard: icon + provider subtitle + a models/badge body row.
function ProviderConfigCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle lines={1} />;
}

interface ProvidersSkeletonProps {
  viewMode?: string;
  configsLabel: string;
  configColumns: SkeletonColumn[];
}

export default function ProvidersSkeleton({
  viewMode,
  configsLabel,
  configColumns,
}: ProvidersSkeletonProps) {
  return (
    <div className="space-y-8">
      <div>
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          {configsLabel}
        </h4>
        <CollectionSkeleton
          viewMode={viewMode}
          columns={configColumns}
          rows={5}
          gridClassName={CARD_GRID_DENSE}
          count={5}
          Card={ProviderConfigCardSkeleton}
        />
      </div>
    </div>
  );
}
