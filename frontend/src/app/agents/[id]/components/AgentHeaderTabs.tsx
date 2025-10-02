import { getTranslations } from "next-intl/server";
import ActiveLink from "./ActiveLink";

export default async function AgentHeaderTabs({ agentId }: { agentId: string }) {
  const t = await getTranslations("Agent");
  return (
    <div className="inline-flex items-center gap-1 rounded-md bg-muted p-1">
      <ActiveLink
        href={`/agents/${agentId}/new-task`}
        className="px-[10px] sm:px-[20px] py-1.5 rounded text-sm"
      >
        {t("createTask")}
      </ActiveLink>
      <ActiveLink
        href={`/agents/${agentId}/tasks`}
        className="px-[10px] sm:px-[20px] py-1.5 rounded text-sm"
      >
        {t("currentTasks")}
      </ActiveLink>
    </div>
  );
}


