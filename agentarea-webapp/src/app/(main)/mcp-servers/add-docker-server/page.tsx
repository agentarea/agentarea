import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import AddDockerServerForm from "./AddDockerServerForm";
import AddDockerServerHeaderControls from "./AddDockerServerHeaderControls";

export default async function AddMCPServerPage() {
  const t = await getTranslations("MCPServersPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/mcp-servers" },
          { label: t("newServer.docker.title") },
        ],
        description: t("newServer.description"),
        backLink: {
          label: "Back to MCP Servers",
          href: "/mcp-servers",
        },
        controls: <AddDockerServerHeaderControls />,
      }}
    >
        <Suspense
          fallback={
            <div className="flex h-32 items-center justify-center">
              <LoadingSpinner />
            </div>
          }
        >
          <AddDockerServerForm />
        </Suspense>
    </ContentBlock>
  );
}
