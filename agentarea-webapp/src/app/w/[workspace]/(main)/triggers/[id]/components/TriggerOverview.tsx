import { getTranslations } from "next-intl/server";
import type {
  AgentResponse,
  ExecutionHistoryResponse,
  ExecutionMetricsResponse,
  TriggerResponse,
} from "@/api/client/types.gen";
import {
  getAgent,
  getStream,
  getTrigger,
  getTriggerExecutions,
  getTriggerMetrics,
  listTriggerCatalog,
} from "@/lib/api";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { getTriggerStatusPresentation } from "@/lib/status";
import { normalizeTaskParameters } from "../../components/taskParameters";
import {
  describeTriggerSchedule,
  findTriggerCatalogEntry,
  getTriggerDisplayName,
  getTriggerHealth,
  type TriggerCatalogEntry,
} from "../../components/triggerDisplay";
import {
  TriggerOverviewView,
  type TriggerOverviewModel,
} from "./TriggerOverviewView";

/** How many past runs the overview shows before deferring to the tab. */
const RECENT_EXECUTIONS = 5;

/**
 * Data container for the trigger overview: loads the trigger, the channel
 * catalog that owns its artwork, its execution metrics, the last few runs and
 * the agent it orchestrates, then hands a plain view model to
 * {@link TriggerOverviewView}.
 */
export async function TriggerOverview({ triggerId }: { triggerId: string }) {
  const trigger = requireApiData<TriggerResponse>(
    await getTrigger(triggerId),
    "trigger"
  );

  const isStream = trigger.trigger_type === "stream";

  // Metrics and history are supporting detail: a trigger that has never run
  // still has an overview, so their failures degrade the page instead of
  // taking it down. No `hours` means the whole history — the page answers
  // "what has this automation done and cost", not "what did it do today".
  const [
    catalogResponse,
    metricsResponse,
    executionsResponse,
    agentResponse,
    streamResponse,
    tCommon,
  ] = await Promise.all([
    listTriggerCatalog(),
    getTriggerMetrics(triggerId),
    getTriggerExecutions(triggerId, {
      page: 1,
      page_size: RECENT_EXECUTIONS,
    }),
    getAgent(trigger.agent_id),
    // A webhook trigger's own backing stream stays unnamed here — only "Last
    // event" ever points at it, so there is nothing to look up.
    isStream && trigger.stream_id
      ? getStream(trigger.stream_id)
      : Promise.resolve(null),
    getTranslations("TriggersPage"),
  ]);

  const catalog = (catalogResponse.data ?? []) as TriggerCatalogEntry[];
  const entry = findTriggerCatalogEntry(trigger, catalog);
  const metrics = metricsResponse.data as ExecutionMetricsResponse | undefined;
  const executions =
    (executionsResponse.data as ExecutionHistoryResponse | undefined)
      ?.executions ?? [];
  const agent = agentResponse.data as AgentResponse | undefined;
  const streamName = streamResponse
    ? optionalApiData(streamResponse, "stream")?.name ?? null
    : null;

  const taskParameters = normalizeTaskParameters(trigger.task_parameters);
  const isCron = trigger.trigger_type === "cron";
  // A stream trigger has no intake of its own: it listens to a stream that
  // something else feeds.
  const hasWebhook = !isCron && !isStream;
  const webhookEndpoint = trigger.webhook_url ?? null;

  const model: TriggerOverviewModel = {
    triggerId,
    name: trigger.name,
    description: trigger.description,
    iconUrl: entry?.icon_url ?? null,
    sourceName: getTriggerDisplayName(trigger, entry),
    // describeTriggerSchedule has no translator to call, so it does not
    // cover stream triggers; the phrase is resolved here instead.
    scheduleText: isStream
      ? tCommon("onStreamEvents")
      : describeTriggerSchedule(trigger),
    status: getTriggerStatusPresentation(getTriggerHealth(trigger)),
    agent: agent ? { id: agent.slug || agent.id, name: agent.name } : null,
    taskText: taskParameters.text,
    skills: taskParameters.skills,
    mcps: taskParameters.mcps,
    files: taskParameters.files,
    cron: isCron
      ? {
          expression: trigger.cron_expression ?? null,
          timezone: trigger.timezone ?? null,
        }
      : null,
    webhook: !hasWebhook
      ? null
      : {
          url: webhookEndpoint,
          methods: trigger.allowed_methods ?? [],
          events: trigger.event_types ?? [],
          signing: trigger.webhook_signing ?? null,
          // The API describes a signing scheme only for webhooks whose secret
          // the platform generates, i.e. the ones that can be rotated here.
          rotatable: Boolean(trigger.signature_scheme),
        },
    failure: {
      consecutive: trigger.consecutive_failures,
      threshold: trigger.failure_threshold,
    },
    needsOwner: trigger.status === "needs_owner",
    isStream,
    stream: trigger.stream_id
      ? {
          id: trigger.stream_id,
          name: streamName,
          lastEventAt: trigger.last_event_at ?? null,
        }
      : null,
    lastExecutionAt: trigger.last_execution_at ?? null,
    nextRunTime: trigger.next_run_time ?? null,
    metrics: metrics
      ? {
          total: metrics.total_executions,
          successful: metrics.successful_executions,
          failed: metrics.failed_executions,
          /** Already a percentage, 0-100. */
          successRate: metrics.success_rate,
          avgMs: metrics.avg_execution_time_ms,
          totalCost: metrics.total_cost_usd ?? 0,
          avgCost: metrics.avg_cost_usd ?? 0,
          costedRuns: metrics.costed_executions ?? 0,
        }
      : null,
    executions,
  };

  return <TriggerOverviewView model={model} />;
}
