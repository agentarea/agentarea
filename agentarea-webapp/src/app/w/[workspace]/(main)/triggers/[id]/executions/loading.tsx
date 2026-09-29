import { TableSkeleton } from "@/components/Skeleton";

// Matches ExecutionsTable: Execution ID · Status · Executed · Duration · Task · Error.
export default function Loading() {
  return (
    <div className="p-6">
      <TableSkeleton
        rows={10}
        columns={[
          { header: "Execution ID", barClassName: "h-4 w-32" },
          { header: "Status", barClassName: "h-5 w-20 rounded-full" },
          { header: "Executed", barClassName: "h-4 w-24" },
          { header: "Duration", barClassName: "h-4 w-16" },
          { header: "Task", barClassName: "h-4 w-24" },
          { header: "Error", barClassName: "h-4 w-28" },
        ]}
      />
    </div>
  );
}
