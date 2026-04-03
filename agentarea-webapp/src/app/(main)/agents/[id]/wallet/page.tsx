import { Suspense } from "react";
import type { Metadata } from "next";
import { LoadingSpinner } from "@/components/LoadingSpinner";
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
    <Suspense
      fallback={
        <div className="flex h-32 items-center justify-center">
          <LoadingSpinner />
        </div>
      }
    >
      <div className="h-full space-y-8 px-4 py-5 overflow-auto">
        <WalletFormContent agentId={resolvedParams.id} />
      </div>
    </Suspense>
  );
}
