import { TableSkeleton } from "@/components/Skeleton";

// Matches PoliciesList: Policy · Value · Category · Effect · Status.
const COLUMNS = [
  { header: "Policy", barClassName: "h-4 w-40" },
  { header: "Value", barClassName: "h-4 w-24" },
  { header: "Category", barClassName: "h-4 w-20" },
  { header: "Effect", barClassName: "h-4 w-16" },
  { header: "Status", barClassName: "h-5 w-20 rounded-full" },
];

export default function PoliciesSkeleton() {
  return <TableSkeleton columns={COLUMNS} rows={8} />;
}
