import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { InboxData } from "./components/InboxData";

export const metadata: Metadata = {
  title: "Inbox",
};

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<{ filter?: string }>;
}) {
  const { filter } = await searchParams;
  const activeFilter = (["all", "pending", "completed", "failed"].includes(filter ?? "")
    ? filter
    : "pending") as "all" | "pending" | "completed" | "failed";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Inbox" }],
      }}
    >
      <Suspense
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <InboxData filter={activeFilter} />
      </Suspense>
    </ContentBlock>
  );
}
