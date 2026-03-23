import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import WorkspaceConfigClient from "./WorkspaceConfigClient";

export const metadata: Metadata = {
  title: "Workspace",
};

export default async function WorkspacePage() {
  const t = await getTranslations("WorkspacePage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Admin", href: "/admin/provider-configs" },
          { label: t("title") },
        ],
        description: t("description"),
      }}
    >
      <WorkspaceConfigClient />
    </ContentBlock>
  );
}
