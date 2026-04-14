import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listAgents } from "@/lib/api";
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
      }}
      className="p-0 overflow-hidden"
    >
      <CreateTriggerForm agents={(agents as any[]) || []} />
    </ContentBlock>
  );
}
