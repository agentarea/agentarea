import { Skeleton } from "@/components/ui/skeleton";

/** `FileBrowser` while its listing loads: the tree, the tab strip, the rows. */
export function FileBrowserSkeleton() {
  return (
    <div className="flex h-full min-h-0 flex-col" aria-hidden="true">
      <div className="flex min-h-0 flex-1">
        <div className="hidden w-64 shrink-0 space-y-3 border-r border-border p-3 sm:block">
          <Skeleton className="h-5 w-2/3 motion-reduce:animate-none" />
          <Skeleton className="h-8 w-full motion-reduce:animate-none" />
          <Skeleton className="h-8 w-4/5 motion-reduce:animate-none" />
          <Skeleton className="h-8 w-3/4 motion-reduce:animate-none" />
          <Skeleton className="h-8 w-5/6 motion-reduce:animate-none" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          {/* The folder / open-file tab strip. */}
          <div className="flex h-9 shrink-0 items-center border-b border-border bg-muted/30 px-3">
            <Skeleton className="h-4 w-24 motion-reduce:animate-none" />
          </div>
          <div className="min-w-0 flex-1 space-y-3 p-4">
            <Skeleton className="h-8 w-2/3 motion-reduce:animate-none" />
            <Skeleton className="h-11 w-full motion-reduce:animate-none" />
            <Skeleton className="h-11 w-full motion-reduce:animate-none" />
            <Skeleton className="h-11 w-full motion-reduce:animate-none" />
            <Skeleton className="h-11 w-full motion-reduce:animate-none" />
          </div>
        </div>
      </div>
    </div>
  );
}
