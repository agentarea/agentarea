import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { getViewerCapabilities } from "@/lib/workspace-context";
import AccessControlData from "./components/access/AccessControlData";
import AccessControlHeaderControls from "./components/access/AccessControlHeaderControls";
import AccessViewTabs from "./components/access/AccessViewTabs";
import { PoliciesData } from "./components/PoliciesData";
import PoliciesHeaderControls from "./components/PoliciesHeaderControls";
import PoliciesSkeleton from "./components/PoliciesSkeleton";
import { PoliciesViewTabs } from "./components/PoliciesViewTabs";

export const metadata: Metadata = {
  title: "Policies",
};

export default async function PoliciesPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  const t = await getTranslations("PoliciesPage");
  const resolved = await searchParams;
  const view = resolved.view === "access" ? "access" : "policies";
  const { canAdminister } = await getViewerCapabilities();

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: !canAdminister ? undefined : view === "access" ? (
          <AccessControlHeaderControls />
        ) : (
          <PoliciesHeaderControls />
        ),
      }}
      subheader={
        <SubheaderToolbar
          categories={<PoliciesViewTabs current={view} />}
          controls={
            canAdminister && view === "access" ? <AccessViewTabs /> : undefined
          }
        />
      }
    >
      {!canAdminister ? (
        <AdminOnlyState
          what={view === "access" ? "accessControl" : "policies"}
        />
      ) : (
        <Suspense fallback={<PoliciesSkeleton view={view} />}>
          {view === "access" ? <AccessControlData /> : <PoliciesData />}
        </Suspense>
      )}
    </ContentBlock>
  );
}
