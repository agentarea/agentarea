import type { Metadata } from "next";
import { Suspense } from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
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

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Policies" }],
        controls:
          view === "access" ? (
            <AccessControlHeaderControls />
          ) : (
            <PoliciesHeaderControls />
          ),
      }}
      subheader={<PoliciesViewTabs current={view} />}
    >
      <div className="main-content">
        <Suspense fallback={<PoliciesSkeleton view={view} />}>
          {view === "access" ? <AccessControlData /> : <PoliciesData />}
        </Suspense>
      </div>
    </ContentBlock>
  );
}
