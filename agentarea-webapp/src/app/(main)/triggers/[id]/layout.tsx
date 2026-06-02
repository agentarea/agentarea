import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTrigger } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import TriggerDetailTabs from "./TriggerDetailTabs";
import TriggerHeaderControls from "./TriggerHeaderControls";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function TriggerLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("TriggersPage");

  const trigger = requireApiData(await getTrigger(id), "trigger");

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
      subheader={<TriggerDetailTabs triggerId={id} />}
    >
      {children}
    </ContentBlock>
  );
}
