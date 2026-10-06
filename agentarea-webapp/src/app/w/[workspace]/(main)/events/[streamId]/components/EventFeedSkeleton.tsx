import { TableSkeleton, type SkeletonColumn } from "@/components/Skeleton";

const COLUMNS: SkeletonColumn[] = [
  { header: "Received", barClassName: "h-3.5 w-28" },
  { header: "Event", barClassName: "h-3.5 w-24" },
  { header: "Key", barClassName: "h-3.5 w-40" },
  { header: "Outcome", barClassName: "h-3.5 w-20" },
];

export default function EventFeedSkeleton({ rows = 10 }: { rows?: number }) {
  return <TableSkeleton columns={COLUMNS} rows={rows} />;
}
