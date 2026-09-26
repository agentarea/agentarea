import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import AuthGuard from "@/components/auth/AuthGuard";
import { WorkplaceData } from "./components/WorkplaceData";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";

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
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center py-8">
              <LoadingSpinner />
            </div>
          }
        >
          <WorkplaceData />
        </Suspense>
      </ContentBlock>
    </AuthGuard>
  );
}
