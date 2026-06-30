import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { Skeleton } from "@/components/ui/skeleton";

// Shown while the workplace page fetches agents/projects/policies on the server.
// Keeps the "Workplace" header; the chat composer + suggestion chips are
// skeletoned in the centered position WorkplaceChat occupies.
export default function WorkplaceLoading() {
  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: "Workplace", href: "/workplace" }] }}
      className="p-0"
    >
      <div className="relative h-full w-full overflow-hidden" aria-hidden="true">
        <div className="absolute inset-0 bg-[url('/lines.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 dark:bg-[url('/lines-dark.png')]" />
        <div className="relative z-[1] flex h-full items-center justify-center p-4">
          <div className="w-full max-w-2xl space-y-4">
            <Skeleton className="mx-auto h-6 w-56" />
            <Skeleton className="h-28 w-full rounded-xl" />
            <div className="flex flex-wrap justify-center gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-32 rounded-full" />
              ))}
            </div>
          </div>
        </div>
      </div>
    </ContentBlock>
  );
}
