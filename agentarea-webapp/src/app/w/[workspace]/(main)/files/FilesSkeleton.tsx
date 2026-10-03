import ContentBlock from "@/components/ContentBlock";
import { Skeleton } from "@/components/ui/skeleton";

export default function FilesSkeleton({ title }: { title: string }) {
  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: title }] }}
      className="min-h-0 overflow-hidden p-0"
    >
      <div className="flex h-full min-h-0 flex-col" aria-hidden="true">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <Skeleton className="h-5 w-28 motion-reduce:animate-none" />
          <Skeleton className="h-9 w-32 motion-reduce:animate-none" />
        </div>
        <div className="flex min-h-0 flex-1">
          <div className="hidden w-64 shrink-0 space-y-3 border-r border-border p-3 sm:block">
            <Skeleton className="h-5 w-2/3 motion-reduce:animate-none" />
            <Skeleton className="h-8 w-full motion-reduce:animate-none" />
            <Skeleton className="h-8 w-4/5 motion-reduce:animate-none" />
            <Skeleton className="h-8 w-3/4 motion-reduce:animate-none" />
            <Skeleton className="h-8 w-5/6 motion-reduce:animate-none" />
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
    </ContentBlock>
  );
}
