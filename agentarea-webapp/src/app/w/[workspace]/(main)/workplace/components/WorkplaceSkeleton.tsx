import { BadgeSuggestionsSkeleton } from "@/components/Chat/componets/BadgeSuggestions";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The workplace while WorkplaceData reads agents, projects and policies:
 * the same lined backdrop, welcome, composer and "Get started" list, in the
 * same places (FullChat's centred layout), so nothing jumps when the chat
 * streams in. The composer keeps its real frame — only what is inside it waits.
 */
export function WorkplaceSkeleton() {
  return (
    <div className="relative h-full w-full overflow-hidden" aria-hidden="true">
      <div className="pointer-events-none absolute inset-0 bg-[url('/lines.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 dark:bg-[url('/lines-dark.png')]" />
      <div className="relative z-[1] h-full p-4">
        <div className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center gap-8 py-8 md:py-0">
          {/* ChatWelcome: icon tile + title */}
          <div className="flex flex-col items-center gap-3">
            <Skeleton className="mb-1 size-9 rounded-sm" />
            <Skeleton className="h-7 w-64" />
          </div>

          {/* FullChat's empty message list still takes a gap here. */}
          <div className="h-0" />

          {/* ChatInputArea */}
          <div className="w-full px-4 pb-3 md:px-6">
            <div className="flex flex-col rounded-xl border border-border bg-background">
              <div className="min-h-[68px] px-4 pb-2 pt-4 sm:min-h-[84px]">
                <Skeleton className="h-3.5 w-56" />
              </div>
              <div className="flex items-center gap-2 px-2.5 pb-2.5">
                <div className="flex h-7 items-center gap-1.5 px-1.5">
                  <Skeleton className="size-5 rounded-[6px]" />
                  <Skeleton className="h-3 w-24" />
                </div>
                <div className="flex h-7 items-center gap-1.5 px-1.5">
                  <Skeleton className="size-3.5 rounded-sm" />
                  <Skeleton className="h-3 w-24" />
                </div>
                <Skeleton className="ml-auto size-8 rounded-md" />
                <Skeleton className="size-8 rounded-md" />
              </div>
            </div>
          </div>

          <div className="w-full pb-4">
            <BadgeSuggestionsSkeleton />
          </div>
        </div>
      </div>
    </div>
  );
}
