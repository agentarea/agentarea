import { getTranslations } from "next-intl/server";
import ActiveLink from "./ActiveLink";
import { MessagesSquare, List, Settings } from "lucide-react";

export default async function AgentHeaderTabs({ agentId }: { agentId: string }) {
  const t = await getTranslations("AgentsPage");
  return (
    <div className="inline-flex items-center gap-3 py-2">
      <ActiveLink
        href={`/agents/${agentId}/new-task`}
      >
        <MessagesSquare className="w-4 h-4" />
        {t("createTask")}
      </ActiveLink>
      <ActiveLink
        href={`/agents/${agentId}/tasks`}
      >
        <List className="w-4 h-4" />
        {t("currentTasks")}
      </ActiveLink>
      <ActiveLink
        href={`/agents/${agentId}/settings`}
      >
        <Settings className="w-4 h-4" />
        {t("settings")}
      </ActiveLink>
    </div>
  );
}


