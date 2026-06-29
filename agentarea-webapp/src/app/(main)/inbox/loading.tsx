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
            <Skeleton key={i} className="h-6 w-20 rounded-md" />
          ))}
        </div>
      }
      className="flex min-h-0 flex-1 flex-col overflow-hidden p-0"
    >
      <div className="min-h-0 flex-1 overflow-hidden" aria-hidden="true">
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className="flex items-start gap-3 border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700"
          >
            <Skeleton className="mt-1 h-4 w-4 shrink-0 rounded-full" />
            <div className="min-w-0 flex-1 space-y-1.5">
              <Skeleton className="h-4 w-2/3" />
              <div className="flex items-center gap-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-16" />
              </div>
            </div>
            <Skeleton className="h-3 w-[62px] shrink-0" />
          </div>
        ))}
      </div>
    </ContentBlock>
  );
}
