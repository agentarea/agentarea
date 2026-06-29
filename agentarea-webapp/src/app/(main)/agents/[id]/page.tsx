import { Suspense } from "react";
import { DetailSkeleton } from "@/components/Skeleton";
import { AgentOverview } from "./components/AgentOverview";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentDetailPage({ params }: Props) {
  const { id } = await params;
  return (
    <div className="main-content">
      <Suspense fallback={<DetailSkeleton />}>
        <AgentOverview agentId={id} />
      </Suspense>
    </div>
  );
}
