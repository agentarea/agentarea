import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading dashboard">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Card key={i} className="gap-3 px-4 py-3.5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-2.5 w-20" />
          </Card>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-12">
        <Skeleton className="h-[300px] rounded-xl lg:col-span-5" />
        <Skeleton className="h-[300px] rounded-xl lg:col-span-7" />
      </div>
      <div className="grid gap-4 lg:grid-cols-12">
        <Skeleton className="h-[520px] rounded-xl lg:col-span-7" />
        <Skeleton className="h-[520px] rounded-xl lg:col-span-5" />
      </div>
    </div>
  );
}
