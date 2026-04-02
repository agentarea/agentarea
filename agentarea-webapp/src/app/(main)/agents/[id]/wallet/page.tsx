import type { Metadata } from "next";
import { WalletConfigPanel } from "@/components/WalletConfig/WalletConfigPanel";

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
    <div className="h-full space-y-8 overflow-auto px-4 py-5">
      <WalletConfigPanel agentId={resolvedParams.id} />
    </div>
  );
}
