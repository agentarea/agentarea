import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listAgents } from "@/lib/api";
import CreateTriggerHeaderControls from "./CreateTriggerHeaderControls";
import { CreateTriggerForm } from "./CreateTriggerForm";

export const metadata = {
  title: "Create Trigger",
};

export default async function CreateTriggerPage() {
  const t = await getTranslations("TriggersPage");
  const tCreate = await getTranslations("TriggersPage.create");

  const { data: agents } = await listAgents();

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
      <CreateTriggerForm agents={agents ?? []} />
    </ContentBlock>
  );
}
