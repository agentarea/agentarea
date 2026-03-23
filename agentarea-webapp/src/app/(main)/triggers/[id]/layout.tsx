import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTrigger, listAgents } from "@/lib/api";
import TriggerDetailTabs from "./TriggerDetailTabs";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function TriggerLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("TriggersPage");

  const { data: trigger } = await getTrigger(id);
  if (!trigger) {
    notFound();
  }

  const { data: agents } = await listAgents();
  const agentName =
    (agents as any[])?.find((a: any) => a.id === (trigger as any).agent_id)
      ?.name || "Unknown Agent";

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/triggers" },
          { label: (trigger as any).name },
        ],
      }}
      className="p-0"
      subheader={
        <TriggerDetailTabs triggerId={id} />
      }
    >
      {children}
    </ContentBlock>
  );
}
