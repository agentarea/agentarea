import { Skeleton } from "@/components/ui/skeleton";

// Approximates BillingClient: a subscription summary card + a usage list.
export default function BillingSkeleton() {
  return (
    <div className="space-y-6" aria-hidden="true">
      <Skeleton className="h-32 w-full rounded-lg" />
      <div className="space-y-2">
        <Skeleton className="h-4 w-32" />
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}
