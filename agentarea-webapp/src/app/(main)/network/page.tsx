import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import NetworkClient from "./NetworkClient";

export const metadata = {
  title: "Network",
};

export default async function NetworkPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Network" }],
        description: "Visual overview of your workspace topology",
      }}
    >
      <Suspense
        fallback={
          <div className="flex h-[calc(100vh-12rem)] items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <NetworkClient />
      </Suspense>
    </ContentBlock>
  );
}
