import { getTranslations } from "next-intl/server";
import AgentPageWrapper from "../shared/AgentPageWrapper";
import CreateAgentContent from "./CreateAgentContent";

export default async function CreateAgentPage() {
  const t = await getTranslations("Agent");
  const tCommon = await getTranslations("Common");

  return (
    <AgentPageWrapper
      breadcrumb={[
        {label: t("browseAgents"), href: "/agents"},
        {label: tCommon("create")},
        {label: t("newAgent")},
      ]}
      useContentBlock={true}
    >
      <CreateAgentContent />
    </AgentPageWrapper>
  );
}
