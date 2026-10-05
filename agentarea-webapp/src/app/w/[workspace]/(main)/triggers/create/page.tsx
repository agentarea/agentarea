import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listAgents, listStreams } from "@/lib/api";
import { CreateTriggerForm } from "./CreateTriggerForm";
import CreateTriggerHeaderControls from "./CreateTriggerHeaderControls";

export const metadata = {
  title: "Create Trigger",
};

export default async function CreateTriggerPage() {
  const t = await getTranslations("TriggersPage");
  const tCreate = await getTranslations("TriggersPage.create");

  const [{ data: agents }, { data: streams }] = await Promise.all([
    listAgents(),
    listStreams(),
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
      <CreateTriggerForm agents={agents ?? []} streams={streams ?? []} />
    </ContentBlock>
  );
}
