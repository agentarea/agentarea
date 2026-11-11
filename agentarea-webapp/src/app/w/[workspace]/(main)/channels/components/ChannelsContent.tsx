import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { listAgents } from "@/lib/api";
import { getTriggerLane } from "../../triggers/components/triggerDisplay";
import { getTriggersCached } from "../../triggers/components/triggersData";
import TriggersTable from "../../triggers/components/TriggersTable";

/** The workspace's channels: stream triggers that carry a conversation. */
export default async function ChannelsContent() {
  const t = await getTranslations("ChannelsPage");
  const [triggers, agents] = await Promise.all([
    getTriggersCached(),
    listAgents(),
  ]);

  if (triggers.error) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        {t("loadFailed")}
      </div>
    );
  }

  const names = new Map((agents.data ?? []).map((a) => [a.id, a.name]));
  const channels = triggers.triggers
    .filter((trigger) => getTriggerLane(trigger) === "channel")
    .map((trigger) => ({
      ...trigger,
      agent_name: names.get(trigger.agent_id),
    }));

  if (channels.length === 0) {
    return (
      <EmptyState
        title={t("empty")}
        description={t("emptyDescription")}
        iconsType="triggers"
        action={{ label: t("new"), href: "/channels/new" }}
      />
    );
  }

  return <TriggersTable triggers={channels} />;
}
