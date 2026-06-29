import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface FormSkeletonProps {
  /** Number of label + input field rows. */
  fields?: number;
  className?: string;
}

/**
 * Loading placeholder for forms that fetch data before rendering (edit forms,
 * create-from-spec). Mirrors a stack of "label + input" rows and a trailing
 * action button — used in place of a spinner while the form's data loads.
 */
export default function FormSkeleton({
  fields = 5,
  className,
}: FormSkeletonProps) {
  return (
    <div className={cn("max-w-2xl space-y-6", className)} aria-hidden="true">
      {Array.from({ length: fields }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-9 w-full rounded-md" />
        </div>
      ))}
      <div className="flex justify-end gap-2 pt-2">
        <Skeleton className="h-9 w-24 rounded-md" />
      </div>
    </div>
  );
}
