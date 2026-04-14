import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { InboxData } from "./components/InboxData";

export const metadata: Metadata = {
  title: "Inbox",
};

export default async function InboxPage() {
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
        <InboxData />
      </Suspense>
    </ContentBlock>
  );
}
