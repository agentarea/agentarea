import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTrigger, listAgents } from "@/lib/api";
import TriggerDetailTabs from "./TriggerDetailTabs";
import TriggerHeaderControls from "./TriggerHeaderControls";

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

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/triggers" },
          { label: (trigger as any).name },
        ],
        controls: (
          <TriggerHeaderControls
            triggerId={id}
            triggerName={(trigger as any).name}
            isActive={(trigger as any).is_active}
          />
        ),
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
