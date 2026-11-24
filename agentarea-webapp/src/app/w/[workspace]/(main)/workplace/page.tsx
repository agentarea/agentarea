import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import AuthGuard from "@/components/auth/AuthGuard";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { WorkplaceData } from "./components/WorkplaceData";
import { WorkplaceSkeleton } from "./components/WorkplaceSkeleton";

export const dynamic = "force-dynamic";

interface WorkplacePageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function WorkplacePage({
  searchParams,
}: WorkplacePageProps) {
  const tPage = await getTranslations("WorkplacePage");
  // A saved task opens here as ?agent=<id>&prompt=<text>: its agent picked and its text in the composer.
  const params = await searchParams;
  const agentId = typeof params.agent === "string" ? params.agent : undefined;
  const prompt = typeof params.prompt === "string" ? params.prompt : undefined;

  return (
    <AuthGuard>
      <ContentBlock
        header={{
          breadcrumb: [{ label: tPage("workplace"), href: "/workplace" }],
        }}
        className="p-0"
      >
        <Suspense fallback={<WorkplaceSkeleton />}>
          <WorkplaceData agentId={agentId} prompt={prompt} />
        </Suspense>
      </ContentBlock>
    </AuthGuard>
  );
}
