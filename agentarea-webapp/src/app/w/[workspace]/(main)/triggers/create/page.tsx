import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listAgents } from "@/lib/api";
import { listTriggerCatalogAction } from "./actions";
import { CreateTriggerForm } from "./CreateTriggerForm";
import CreateTriggerHeaderControls from "./CreateTriggerHeaderControls";
import { loadStreamOptions } from "./streamOptions";

export const metadata = {
  title: "Create Trigger",
};

export default async function CreateTriggerPage() {
  const t = await getTranslations("TriggersPage");
  const tCreate = await getTranslations("TriggersPage.create");

  const [{ data: agents }, catalog, streams] = await Promise.all([
    listAgents(),
    listTriggerCatalogAction().catch((error) => {
      console.error("Failed to load trigger catalog:", error);
      return null;
    }),
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
      className="p-0"
    >
      <CreateTriggerForm
        agents={agents ?? []}
        catalog={catalog}
        streams={streams}
      />
    </ContentBlock>
  );
}
