import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { PoliciesData } from "./components/PoliciesData";
import PoliciesHeaderControls from "./components/PoliciesHeaderControls";
import PoliciesSkeleton from "./components/PoliciesSkeleton";

export const metadata: Metadata = {
  title: "Policies",
};

export default async function PoliciesPage() {
  const t = await getTranslations("PoliciesPage");
  const { canAdminister } = await getViewerCapabilities();

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: canAdminister ? <PoliciesHeaderControls /> : undefined,
      }}
    >
      {!canAdminister ? (
        <AdminOnlyState what="policies" />
      ) : (
        <Suspense fallback={<PoliciesSkeleton />}>
          <PoliciesData />
        </Suspense>
      )}
    </ContentBlock>
  );
}
