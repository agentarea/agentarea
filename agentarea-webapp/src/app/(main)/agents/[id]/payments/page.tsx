import type { Metadata } from "next";
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
  const resolvedParams = await params;

  return (
    <div className="h-full space-y-2 overflow-auto px-4 py-5">
      <PaymentHistoryTable agentId={resolvedParams.id} />
    </div>
  );
}
