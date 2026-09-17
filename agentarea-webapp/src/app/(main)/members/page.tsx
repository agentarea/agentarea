import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { getWorkspaceContext } from "@/lib/workspace-context";
import MembersData from "./MembersData";
import MembersSkeleton from "./MembersSkeleton";

export const metadata: Metadata = {
  title: "Members",
};

export default async function MembersPage() {
  const t = await getTranslations("MembersPage");
  const { active } = await getWorkspaceContext();

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        // Removing someone is irreversible, so the page states which workspace
        // it is acting on rather than leaving it to the switcher.
        description: active
          ? t("descriptionForWorkspace", { workspace: active.name })
          : t("description"),
      }}
    >
      <div className="main-content">
        <Suspense fallback={<MembersSkeleton />}>
          <MembersData />
        </Suspense>
      </div>
    </ContentBlock>
  );
}
