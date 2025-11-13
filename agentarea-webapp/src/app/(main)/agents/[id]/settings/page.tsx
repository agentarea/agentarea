import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import AgentEditContent from "./AgentEditContent";

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
