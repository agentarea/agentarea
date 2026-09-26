import { TableSkeleton } from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";

// Matches PoliciesList: Policy · Value · Category · Effect · Status.
const COLUMNS = [
  { header: "Policy", barClassName: "h-4 w-40" },
  { header: "Value", barClassName: "h-4 w-24" },
  { header: "Category", barClassName: "h-4 w-20" },
  { header: "Effect", barClassName: "h-4 w-16" },
  { header: "Status", barClassName: "h-5 w-20 rounded-full" },
];

// The Access view is a query-builder + interactive graph; approximate it with a
// narrow control column and a large canvas block rather than a faithful graph.
function AccessSkeleton() {
  return (
    <div className="flex gap-6">
      <div className="hidden w-64 shrink-0 flex-col gap-3 lg:flex">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-[60vh] flex-1 rounded-lg" />
    </div>
  );
}

interface PoliciesSkeletonProps {
  view: "access" | "policies";
}

export default function PoliciesSkeleton({ view }: PoliciesSkeletonProps) {
  if (view === "access") return <AccessSkeleton />;
  return <TableSkeleton columns={COLUMNS} rows={8} />;
}
