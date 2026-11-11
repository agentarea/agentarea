import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listAgents, listStreamSourceTypes } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { isChannelType } from "./channelRequest";
import { CreateChannelForm } from "./CreateChannelForm";
import CreateChannelHeaderControls from "./CreateChannelHeaderControls";

export const metadata = { title: "New channel" };

export default async function CreateChannelPage() {
  const t = await getTranslations("ChannelsPage");
  const [types, agents] = await Promise.all([
    listStreamSourceTypes(),
    listAgents(),
  ]);
  const channelTypes = requireApiData(types, t("create.typesFailed")).filter(
    isChannelType
  );
  const selectable = requireApiData(agents, t("create.agentsFailed")).map(
    (agent) => ({
      id: agent.id,
      name: agent.name,
      description: agent.description,
    })
  );

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/channels" },
          { label: t("create.title") },
        ],
        controls: <CreateChannelHeaderControls />,
      }}
    >
      <CreateChannelForm types={channelTypes} agents={selectable} />
    </ContentBlock>
  );
}
