import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";

const GRID_CLASS =
  "grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5";

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
      gridClassName={GRID_CLASS}
      count={10}
      Card={TaskCardSkeleton}
    />
  );
}
