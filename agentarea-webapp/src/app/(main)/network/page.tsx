import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getAuthContext } from "@/lib/getAuthContext";
import NetworkClient, {
  NetworkHeaderControls,
  NetworkHeaderTabs,
} from "./NetworkClient";
import { NetworkProvider } from "./NetworkProvider";

export default async function NetworkPage() {
  const { userId, workspaceId } = await getAuthContext();
  // Workspace switching refreshes RSC while preserving client state unless keyed.
  const scopeKey = JSON.stringify([userId, workspaceId]);
  return (
    <NetworkProvider key={scopeKey}>
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
