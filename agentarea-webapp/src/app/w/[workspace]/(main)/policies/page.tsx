import { Suspense } from "react";
import type { Metadata } from "next";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getViewerCapabilities } from "@/lib/workspace-context";
import AccessControlData from "./components/access/AccessControlData";
import AccessControlHeaderControls from "./components/access/AccessControlHeaderControls";
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
  const resolved = await searchParams;
  const view = resolved.view === "access" ? "access" : "policies";
  const { canAdminister } = await getViewerCapabilities();

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Policies" }],
        controls: !canAdminister ? undefined : view === "access" ? (
          <AccessControlHeaderControls />
        ) : (
          <PoliciesHeaderControls />
        ),
      }}
      subheader={<PoliciesViewTabs current={view} />}
    >
      <div className="main-content">
        {!canAdminister ? (
          <AdminOnlyState
            what={view === "access" ? "accessControl" : "policies"}
          />
        ) : (
          <Suspense fallback={<PoliciesSkeleton view={view} />}>
            {view === "access" ? <AccessControlData /> : <PoliciesData />}
          </Suspense>
        )}
      </div>
    </ContentBlock>
  );
}
