import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { Skeleton } from "@/components/ui/skeleton";

// Shown while the inbox page fetches on the server. Keeps the real "Inbox"
// breadcrumb; the toolbar counts and task list are skeletoned (they need data).
export default function InboxLoading() {
  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: "Inbox" }] }}
      subheader={
        <div className="flex items-center gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-7 w-24 rounded-md" />
          ))}
        </div>
      }
      className="flex min-h-0 flex-1 flex-col overflow-hidden p-0"
    >
      <div className="min-h-0 flex-1 overflow-hidden" aria-hidden="true">
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700"
          >
            <Skeleton className="h-6 w-6 shrink-0 rounded-[7px]" />
            <div className="min-w-0 flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-2/3" />
              <div className="flex items-center gap-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-16" />
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <Skeleton className="h-3.5 w-3.5 rounded-full" />
              <Skeleton className="h-3 w-[62px]" />
            </div>
          </div>
        ))}
      </div>
    </ContentBlock>
  );
}
