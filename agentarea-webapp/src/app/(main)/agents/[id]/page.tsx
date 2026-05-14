import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { AgentOverview } from "./components/AgentOverview";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentDetailPage({ params }: Props) {
  const { id } = await params;
  return (
    <div className="main-content">
      <Suspense
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <AgentOverview agentId={id} />
      </Suspense>
    </div>
  );
}
