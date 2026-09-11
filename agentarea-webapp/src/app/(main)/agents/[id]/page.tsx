import { Suspense } from "react";
import { AgentOverview } from "./components/AgentOverview";
import AgentOverviewSkeleton from "./components/AgentOverviewSkeleton";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentDetailPage({ params }: Props) {
  const { id } = await params;
  return (
    <div className="h-full overflow-auto md:overflow-hidden">
      <Suspense fallback={<AgentOverviewSkeleton />}>
        <AgentOverview agentId={id} />
      </Suspense>
    </div>
  );
}
