import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { FormSkeleton } from "@/components/Skeleton";
import { loadEgressExitChoices } from "../egressExitsData";
import { AddMCPServerForm } from "./form";
import AddMCPServerHeaderControls from "./header-controls";

export const metadata: Metadata = {
  title: "Add MCP Server",
};

async function AddMCPServerFormData() {
  return <AddMCPServerForm egressExits={await loadEgressExitChoices()} />;
}

export default async function AddMCPServerPage() {
  const t = await getTranslations("MCPServersPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/connections" },
          { label: t("newServer.title") },
        ],
        controls: <AddMCPServerHeaderControls />,
      }}
    >
      <Suspense fallback={<FormSkeleton />}>
        <AddMCPServerFormData />
      </Suspense>
    </ContentBlock>
  );
}
