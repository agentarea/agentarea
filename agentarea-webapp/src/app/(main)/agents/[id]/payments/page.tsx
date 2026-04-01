import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PaymentHistoryTable } from "@/components/PaymentHistory";
import ContentBlock from "@/components/ContentBlock/ContentBlock";

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
  const t = await getTranslations("AgentPaymentsPage");
  const t_sidebar = await getTranslations("Sidebar");

  return (
    <div className="h-full space-y-2 overflow-auto px-4 py-5">
      <PaymentHistoryTable agentId={resolvedParams.id} />
    </div>  
  );
}
