import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listAgents } from "@/lib/api";
import { CreateTriggerForm } from "./CreateTriggerForm";
import CreateTriggerHeaderControls from "./CreateTriggerHeaderControls";
import { loadStreamOptions } from "./streamOptions";

export const metadata = {
  title: "Create Trigger",
};

export default async function CreateTriggerPage() {
  const t = await getTranslations("TriggersPage");
  const tCreate = await getTranslations("TriggersPage.create");

  const [{ data: agents }, streams] = await Promise.all([
    listAgents(),
    loadStreamOptions(tCreate("streamsLoadFailed")),
  ]);

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
    >
      <CreateTriggerForm agents={agents ?? []} streams={streams} />
    </ContentBlock>
  );
}
