import { Suspense } from "react";
import type { Metadata } from "next";
import { FormSkeleton } from "@/components/Skeleton";
import WalletFormContent from "./WalletFormContent";

export const metadata: Metadata = {
  title: "Agent Wallet & Payments",
};

interface AgentWalletPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function AgentWalletPage({
  params,
}: AgentWalletPageProps) {
  const resolvedParams = await params;

  return (
    <Suspense fallback={<FormSkeleton className="px-4 py-5" />}>
      <div className="h-full space-y-8 px-4 py-5 overflow-auto">
        <WalletFormContent agentId={resolvedParams.id} />
      </div>
    </Suspense>
  );
}
