import { getTranslations } from "next-intl/server";
import type {
  ExecutionMetricsResponse,
  TriggerResponse,
} from "@/api/client/types.gen";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTrigger, getTriggerMetrics } from "@/lib/api";
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

  // Best-effort run count for the Executions tab pill; a failed lookup just
  // hides the number.
  const [triggerResponse, metricsResponse] = await Promise.all([
    getTrigger(id),
    getTriggerMetrics(id).catch(() => ({ data: undefined })),
  ]);
  const trigger = requireApiData(triggerResponse, "trigger") as TriggerResponse;
  const executionCount = (
    metricsResponse.data as ExecutionMetricsResponse | undefined
  )?.total_executions;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/triggers" },
          { label: trigger.name, href: `/triggers/${id}` },
        ],
        controls: (
          <TriggerHeaderControls
            triggerId={id}
            triggerName={trigger.name}
            isActive={trigger.is_active}
          />
        ),
      }}
      className="p-0"
      subheader={
        <TriggerDetailTabs triggerId={id} executionCount={executionCount} />
      }
    >
      {children}
    </ContentBlock>
  );
}
