import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { FormSkeleton } from "@/components/Skeleton";
import { AddMCPServerForm } from "./form";
import AddMCPServerHeaderControls from "./header-controls";

export default async function AddMCPServerPage() {
  const t = await getTranslations("MCPServersPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/mcp-servers" },
          { label: "Add Server" },
        ],
        description: "Connect an MCP server to your workspace",
        backLink: {
          label: "Back to MCP Servers",
          href: "/mcp-servers",
        },
        controls: <AddMCPServerHeaderControls />,
      }}
    >
      <Suspense fallback={<FormSkeleton />}>
        <AddMCPServerForm />
      </Suspense>
    </ContentBlock>
  );
}
