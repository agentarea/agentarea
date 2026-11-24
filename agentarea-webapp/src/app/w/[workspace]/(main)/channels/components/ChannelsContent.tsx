import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import ChannelsScene from "@/components/illustrations/ChannelsScene";
import { listAgents, listStreams, listStreamSourceTypes } from "@/lib/api";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { getTriggerLane } from "../../triggers/components/triggerDisplay";
import { getTriggersCached } from "../../triggers/components/triggersData";
import TriggersTable from "../../triggers/components/TriggersTable";

/** The workspace's channels: stream triggers that carry a conversation. */
export default async function ChannelsContent() {
  const t = await getTranslations("ChannelsPage");
  const [triggers, agents, streams, sourceTypes] = await Promise.all([
    getTriggersCached(),
    listAgents(),
    listStreams(),
    listStreamSourceTypes(),
  ]);

  if (triggers.error) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        {t("loadFailed")}
      </div>
    );
  }
  if (streams.error) {
    console.error(
      "Failed to load the streams channels listen to",
      streams.error
    );
  }
  if (sourceTypes.error) {
    console.error("Failed to load the source type catalog", sourceTypes.error);
  }

  const names = new Map((agents.data ?? []).map((a) => [a.id, a.name]));
  const types = sourceTypes.data ?? [];
  const feeds = new Map(
    (streams.data ?? []).map((stream) => [
      stream.id,
      {
        name: stream.name,
        types: stream.source_types
          .map((slug) => sourceTypeBySlug(types, slug))
          .filter((type): type is SourceType => type !== undefined),
      },
    ])
  );
  const channels = triggers.triggers
    .filter((trigger) => getTriggerLane(trigger) === "channel")
    .map((trigger) => {
      const feed = trigger.stream_id ? feeds.get(trigger.stream_id) : undefined;
      return {
        ...trigger,
        agent_name: names.get(trigger.agent_id),
        stream_name: feed?.name,
        source_types: feed?.types,
      };
    });

  if (channels.length === 0) {
    return (
      <EmptyState
        title={t("empty")}
        visual={<ChannelsScene />}
        description={t("emptyDescription")}
        action={{ label: t("new"), href: "/channels/new" }}
      />
    );
  }

  return <TriggersTable triggers={channels} />;
}
