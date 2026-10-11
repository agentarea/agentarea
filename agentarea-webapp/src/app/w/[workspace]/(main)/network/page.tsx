import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getAuthContext } from "@/lib/getAuthContext";
import NetworkClient, {
  NetworkHeaderControls,
  NetworkToolbar,
} from "./NetworkClient";
import { NetworkProvider } from "./NetworkProvider";

export default async function NetworkPage() {
  const { userId, workspaceId } = await getAuthContext();
  const t = await getTranslations("NetworkPage");
  // Workspace switching refreshes RSC while preserving client state unless keyed.
  const scopeKey = JSON.stringify([userId, workspaceId]);
  return (
    <NetworkProvider key={scopeKey}>
      <ContentBlock
        header={{
          breadcrumb: [{ label: t("title") }],
          controls: <NetworkHeaderControls />,
        }}
        subheader={<NetworkToolbar />}
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
