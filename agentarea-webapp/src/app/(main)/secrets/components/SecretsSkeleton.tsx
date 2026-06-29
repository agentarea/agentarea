import { TableSkeleton } from "@/components/Skeleton";

// Matches SecretsTable: Connection name · Auth type · Status · Created.
const COLUMNS = [
  { header: "Connection name", barClassName: "h-4 w-40" },
  { header: "Auth type", barClassName: "h-4 w-20" },
  { header: "Status", barClassName: "h-5 w-20 rounded-full" },
  { header: "Created", barClassName: "h-4 w-24" },
];

export default function SecretsSkeleton() {
  return (
    <div className="space-y-6">
      <TableSkeleton columns={COLUMNS} rows={8} />
    </div>
  );
}
