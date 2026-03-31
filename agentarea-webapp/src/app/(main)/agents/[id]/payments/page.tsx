import type { Metadata } from "next";
import { PaymentHistoryTable } from "@/components/PaymentHistory";

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
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Payment History</h2>
        <p className="text-sm text-muted-foreground">
          All service payments made by this agent via x402 and MPP protocols.
        </p>
      </div>
      <PaymentHistoryTable agentId={resolvedParams.id} />
    </div>
  );
}
