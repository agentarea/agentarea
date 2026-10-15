import Divider from "@/components/ui/divider";
import { Skeleton } from "@/components/ui/skeleton";

/** A `FormLabel`: its icon plate and the label text. */
function LabelSkeleton({ width = "w-28" }: { width?: string }) {
  return (
    <div className="flex items-center gap-[5px]">
      <Skeleton className="h-[22px] w-[22px] rounded-sm" />
      <Skeleton className={`h-3 ${width}`} />
    </div>
  );
}

function FieldSkeleton({
  label,
  inputClassName = "h-9",
}: {
  label?: string;
  inputClassName?: string;
}) {
  return (
    <div className="space-y-2">
      <LabelSkeleton width={label} />
      <Skeleton className={`w-full rounded-md ${inputClassName}`} />
    </div>
  );
}

/** One of the agent panel's sections: its header strip and a row. */
function PanelSectionSkeleton() {
  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className="border-b border-border bg-sidebar px-3 py-1.5">
        <Skeleton className="h-2.5 w-20" />
      </div>
      <div className="p-3">
        <Skeleton className="h-3 w-32" />
      </div>
    </div>
  );
}

/**
 * The saved trigger's form while it loads, laid out as `CreateTriggerForm`
 * renders it on /edit: name, task, the chosen type with its settings and the
 * run settings on the left; the agent and its context in the right panel.
 */
export default function TriggerFormSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="flex h-full flex-col overflow-hidden lg:flex-row"
    >
      <div className="min-w-0 flex-1 px-4 py-5">
        <div className="mx-auto w-full max-w-4xl space-y-5">
          <FieldSkeleton label="w-40" />
          <FieldSkeleton label="w-16" inputClassName="h-[200px]" />
          <Divider />
          <div className="space-y-2">
            <LabelSkeleton width="w-24" />
            <Skeleton className="h-2.5 w-20" />
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              <Skeleton className="h-[54px] w-full rounded-lg" />
            </div>
          </div>
          <FieldSkeleton label="w-24" />
          <div className="md:max-w-sm">
            <FieldSkeleton label="w-24" />
          </div>
          <Divider />
          <LabelSkeleton width="w-32" />
        </div>
      </div>
      <div className="border-t border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-800 lg:h-full lg:w-[360px] lg:shrink-0 lg:border-l lg:border-t-0">
        <div className="space-y-4 px-3.5 py-3">
          <Skeleton className="h-2.5 w-32" />
          <FieldSkeleton label="w-24" />
          <PanelSectionSkeleton />
          <PanelSectionSkeleton />
          <PanelSectionSkeleton />
        </div>
      </div>
    </div>
  );
}
