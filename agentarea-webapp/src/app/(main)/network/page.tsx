"use client";

import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import NetworkClient, {
  NetworkHeaderControls,
  NetworkHeaderTabs,
} from "./NetworkClient";
import { NetworkProvider } from "./NetworkProvider";

export default function NetworkPage() {
  return (
    <NetworkProvider>
      <ContentBlock
        header={{
          breadcrumb: [{ label: "Network topology" }],
          controls: <NetworkHeaderControls />,
        }}
        subheader={<NetworkHeaderTabs />}
        className="p-0"
      >
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center">
              <LoadingSpinner />
            </div>
          }
        >
          <NetworkClient />
        </Suspense>
      </ContentBlock>
    </NetworkProvider>
  );
}
