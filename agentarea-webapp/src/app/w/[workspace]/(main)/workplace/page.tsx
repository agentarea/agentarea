import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import AuthGuard from "@/components/auth/AuthGuard";
import { WorkplaceData } from "./components/WorkplaceData";
import { WorkplaceSkeleton } from "./components/WorkplaceSkeleton";
import ContentBlock from "@/components/ContentBlock/ContentBlock";

export const dynamic = "force-dynamic";

export default async function WorkplacePage() {
  const tPage = await getTranslations("WorkplacePage");

  return (
    <AuthGuard>
      <ContentBlock
        header={{
          breadcrumb: [{ label: tPage("workplace"), href: "/workplace" }],
        }}
        className="p-0"
      >
        <Suspense fallback={<WorkplaceSkeleton />}>
          <WorkplaceData />
        </Suspense>
      </ContentBlock>
    </AuthGuard>
  );
}
