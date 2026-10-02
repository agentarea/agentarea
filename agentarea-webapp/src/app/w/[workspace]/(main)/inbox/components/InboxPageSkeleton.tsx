import { useTranslations } from "next-intl";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { Skeleton } from "@/components/ui/skeleton";
import { FILTER_KEYS } from "./inboxShared";

/**
 * The inbox while its tasks load: the real "Inbox" header, one placeholder per
 * filter tab, and the list column at the width InboxClient gives it, with the
 * detail pane beside it on wide screens. Used by the route's loading.tsx and by
 * the page's own Suspense boundary, so the frame never changes under the user.
 */
export function InboxPageSkeleton() {
  const t = useTranslations("InboxPage");

  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: t("title") }] }}
      subheader={
        <div className="flex items-center gap-2" aria-hidden="true">
          {FILTER_KEYS.map((key) => (
            <Skeleton key={key} className="h-7 w-24 rounded-md" />
          ))}
        </div>
      }
      className="flex min-h-0 flex-1 flex-col overflow-hidden p-0"
    >
      <div className="flex min-h-0 flex-1 overflow-hidden" aria-hidden="true">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden lg:w-[40%] lg:min-w-[360px] lg:max-w-[520px] lg:flex-none lg:border-r lg:border-border">
          {Array.from({ length: 10 }).map((_, i) => (
            // Mirrors an InteractiveListRow in InboxTaskList: avatar, title,
            // agent + preview line, then status and age on the right.
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
        <div className="hidden min-w-0 flex-1 bg-background lg:block" />
      </div>
    </ContentBlock>
  );
}
