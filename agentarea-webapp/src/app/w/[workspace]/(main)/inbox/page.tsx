import type { Metadata } from "next";
import { Suspense } from "react";
import { InboxData } from "./components/InboxData";
import { InboxPageSkeleton } from "./components/InboxPageSkeleton";

export const metadata: Metadata = {
  title: "Inbox",
};

export default function InboxPage() {
  return (
    <Suspense fallback={<InboxPageSkeleton />}>
      <InboxData />
    </Suspense>
  );
}
