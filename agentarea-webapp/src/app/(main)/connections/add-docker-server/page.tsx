import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { FormSkeleton } from "@/components/Skeleton";
import AddDockerServerForm from "./AddDockerServerForm";
import AddDockerServerHeaderControls from "./AddDockerServerHeaderControls";

export default async function AddMCPServerPage() {
  const t = await getTranslations("MCPServersPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/connections" },
          { label: t("newServer.docker.title") },
        ],
        description: t("newServer.description"),
        backLink: {
          label: "Back to MCP Servers",
          href: "/connections",
        },
        controls: <AddDockerServerHeaderControls />,
      }}
    >
        <Suspense fallback={<FormSkeleton />}>
          <AddDockerServerForm />
        </Suspense>
    </ContentBlock>
  );
}
