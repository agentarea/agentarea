import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import { CARD_GRID_WIDE } from "@/lib/collectionGrids";

// TaskItem: status badge top-right, body = agent row + date/time row.
function TaskCardSkeleton() {
  return <LinkedCardSkeleton topRight lines={2} />;
}

interface TasksSkeletonProps {
  viewMode?: string;
  columns: SkeletonColumn[];
}

export default function TasksSkeleton({ viewMode, columns }: TasksSkeletonProps) {
  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={columns}
      rows={8}
      gridClassName={CARD_GRID_WIDE}
      count={10}
      Card={TaskCardSkeleton}
    />
  );
}
