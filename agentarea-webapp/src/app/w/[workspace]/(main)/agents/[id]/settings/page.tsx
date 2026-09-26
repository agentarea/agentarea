import { Suspense } from "react";
import type { Metadata } from "next";
import { FormSkeleton } from "@/components/Skeleton";
import AgentEditContent from "./AgentEditContent";

export const metadata: Metadata = {
  title: "Agent Settings",
};

interface AgentSettingsPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function AgentSettingsPage({
  params,
}: AgentSettingsPageProps) {
  const resolvedParams = await params;

  return (
    <Suspense fallback={<FormSkeleton className="p-4" />}>
      <AgentEditContent agentId={resolvedParams.id} />
    </Suspense>
  );
}
