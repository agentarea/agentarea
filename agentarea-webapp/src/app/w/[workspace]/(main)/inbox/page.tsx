import type { Metadata } from "next";
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { InboxData } from "./components/InboxData";

export const metadata: Metadata = {
  title: "Inbox",
};

export default function InboxPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center py-8">
          <LoadingSpinner />
        </div>
      }
    >
      <InboxData />
    </Suspense>
  );
}
