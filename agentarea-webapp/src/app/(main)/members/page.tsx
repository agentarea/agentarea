import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import MembersData from "./MembersData";
import MembersSkeleton from "./MembersSkeleton";

export const metadata: Metadata = {
  title: "Members",
};

export default async function MembersPage() {
  const t = await getTranslations("MembersPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
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
