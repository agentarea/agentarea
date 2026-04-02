import { Suspense } from "react";
import type { Metadata } from "next";
import { LoadingSpinner } from "@/components/LoadingSpinner";
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
    <Suspense
      fallback={
        <div className="flex h-32 items-center justify-center">
          <LoadingSpinner />
        </div>
      }
    >
      <AgentEditContent agentId={resolvedParams.id} />
    </Suspense>
  );
}
