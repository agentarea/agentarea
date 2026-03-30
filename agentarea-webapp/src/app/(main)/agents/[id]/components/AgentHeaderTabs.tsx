import { getTranslations } from "next-intl/server";
import { CreditCard, List, MessagesSquare, Settings } from "lucide-react";
import { ActiveLink } from "@/components/ui/active-link";

export default async function AgentHeaderTabs({
  agentId,
}: {
  agentId: string;
}) {
  const t = await getTranslations("AgentsPage");
  return (
    <div className="inline-flex items-center gap-3 py-2">
      <ActiveLink href={`/agents/${agentId}/new-task`}>
        <MessagesSquare className="h-4 w-4" />
        {t("createTask")}
      </ActiveLink>
      <ActiveLink href={`/agents/${agentId}/tasks`}>
        <List className="h-4 w-4" />
        {t("currentTasks")}
      </ActiveLink>
      <ActiveLink href={`/agents/${agentId}/payments`}>
        <CreditCard className="h-4 w-4" />
        Payments
      </ActiveLink>
      <ActiveLink href={`/agents/${agentId}/settings`}>
        <Settings className="h-4 w-4" />
        {t("settings")}
      </ActiveLink>
    </div>
  );
}
