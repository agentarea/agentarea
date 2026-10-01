import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";
import { CARD_GRID_DENSE, CARD_GRID_GALLERY } from "@/lib/collectionGrids";

// ProviderConfigCard: icon + provider subtitle + a models/badge body row.
function ProviderConfigCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle lines={1} />;
}

interface ProvidersSkeletonProps {
  viewMode?: string;
  configsLabel: string;
  configColumns: SkeletonColumn[];
}

// Connected tab: the configs section. The catalog lives on the Available tab.
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

// Available-tab card: logo + name/key, two description lines, the
// type · models line and the built-in badge.
function ProviderSpecCardSkeleton() {
  return (
    <div className="card card-shadow cursor-default" aria-hidden="true">
      <div className="flex flex-col gap-2">
        <div className="mb-2 flex items-center gap-3">
          <Skeleton className="h-8 w-8 rounded" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-3 w-16" />
          </div>
        </div>
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-2/3" />
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-5 w-16 rounded-full" />
      </div>
    </div>
  );
}

export function ProviderSpecsSkeleton({
  viewMode,
  columns,
}: {
  viewMode?: string;
  columns: SkeletonColumn[];
}) {
  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={columns}
      rows={8}
      gridClassName={CARD_GRID_GALLERY}
      count={10}
      Card={ProviderSpecCardSkeleton}
    />
  );
}
