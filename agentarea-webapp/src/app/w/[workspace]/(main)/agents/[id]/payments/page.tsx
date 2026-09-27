import type { Metadata } from "next";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { PaymentHistoryTable } from "./components/PaymentHistoryTable";

export const metadata: Metadata = {
  title: "Agent Payments",
};

interface AgentPaymentsPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function AgentPaymentsPage({
  params,
}: AgentPaymentsPageProps) {
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
    <div className="h-full space-y-2 overflow-auto px-4 py-5">
      <PaymentHistoryTable agentId={resolvedParams.id} />
    </div>
  );
}
