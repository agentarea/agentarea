import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listAgents } from "@/lib/api";
import { CreateTriggerForm } from "./CreateTriggerForm";
import CreateTriggerHeaderControls from "./CreateTriggerHeaderControls";
import { loadStreamOptions } from "./streamOptions";

export const metadata = {
  title: "Create Trigger",
};

export default async function CreateTriggerPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("TriggersPage");
  const tCreate = await getTranslations("TriggersPage.create");

  const [{ data: agents }, streams, query] = await Promise.all([
    listAgents(),
    loadStreamOptions(tCreate("streamsLoadFailed")),
    searchParams,
  ]);
  const presetStream = streams.items.find((s) => s.id === query.stream);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/triggers" },
          { label: tCreate("title") },
        ],
        controls: (
          <CreateTriggerHeaderControls label={tCreate("createButton")} />
        ),
      }}
      className="p-0"
    >
      <CreateTriggerForm
        agents={agents ?? []}
        streams={streams}
        preset={presetStream && { streamId: presetStream.id }}
      />
    </ContentBlock>
  );
}
