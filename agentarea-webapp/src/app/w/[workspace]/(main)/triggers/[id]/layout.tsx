import { getTranslations } from "next-intl/server";
import type {
  ExecutionMetricsResponse,
  TriggerResponse,
} from "@/api/client/types.gen";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTrigger, getTriggerMetrics } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import TriggerDetailTabs from "./TriggerDetailTabs";
import { TriggerDetailStatusProvider } from "./TriggerDetailStatus";
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
    getTriggerMetrics(id).catch((error: unknown) => ({
      data: undefined,
      error,
    })),
  ]);
  if (metricsResponse.error) {
    console.error(
      "Failed to load trigger metrics for the tab count",
      metricsResponse.error
    );
  }
  const trigger = requireApiData(triggerResponse, "trigger") as TriggerResponse;
  const executionCount = (
    metricsResponse.data as ExecutionMetricsResponse | undefined
  )?.total_executions;

  return (
    <TriggerDetailStatusProvider key={id} initialActive={trigger.is_active}>
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
    </TriggerDetailStatusProvider>
  );
}
