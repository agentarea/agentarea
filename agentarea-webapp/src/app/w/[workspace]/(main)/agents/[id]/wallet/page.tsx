import { Suspense } from "react";
import type { Metadata } from "next";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import { FormSkeleton } from "@/components/Skeleton";
import { getViewerCapabilities } from "@/lib/workspace-context";
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
  const [resolvedParams, { canAdminister }] = await Promise.all([
    params,
    getViewerCapabilities(),
  ]);

  if (!canAdminister) {
    return (
      <div className="h-full px-4 py-5">
        <AdminOnlyState what="wallet" />
      </div>
    );
  }

  return (
    <Suspense fallback={<FormSkeleton className="px-4 py-5" />}>
      <div className="h-full space-y-8 px-4 py-5 overflow-auto">
        <WalletFormContent agentId={resolvedParams.id} />
      </div>
    </Suspense>
  );
}
