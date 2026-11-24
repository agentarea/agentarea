import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getAuthContext } from "@/lib/getAuthContext";
import NetworkClient, {
  NetworkGraphSkeleton,
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
        }}
        subheader={<NetworkToolbar />}
        className="p-0"
      >
        <Suspense fallback={<NetworkGraphSkeleton />}>
          <NetworkClient />
        </Suspense>
      </ContentBlock>
    </NetworkProvider>
  );
}
