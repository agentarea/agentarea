import type {
  AgentResponse,
  ExecutionHistoryResponse,
  ExecutionMetricsResponse,
  TriggerResponse,
} from "@/api/client/types.gen";
import {
  getAgent,
  getTrigger,
  getTriggerExecutions,
  getTriggerMetrics,
  listTriggerCatalog,
} from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
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

  // Metrics and history are supporting detail: a trigger that has never run
  // still has an overview, so their failures degrade the page instead of
  // taking it down. No `hours` means the whole history — the page answers
  // "what has this automation done and cost", not "what did it do today".
  const [catalogResponse, metricsResponse, executionsResponse, agentResponse] =
    await Promise.all([
      listTriggerCatalog(),
      getTriggerMetrics(triggerId),
      getTriggerExecutions(triggerId, {
        page: 1,
        page_size: RECENT_EXECUTIONS,
      }),
      getAgent(trigger.agent_id),
    ]);

  const catalog = (catalogResponse.data ?? []) as TriggerCatalogEntry[];
  const entry = findTriggerCatalogEntry(trigger, catalog);
  const metrics = metricsResponse.data as ExecutionMetricsResponse | undefined;
  const executions =
    (executionsResponse.data as ExecutionHistoryResponse | undefined)
      ?.executions ?? [];
  const agent = agentResponse.data as AgentResponse | undefined;

  const taskParameters = normalizeTaskParameters(trigger.task_parameters);
  const isCron = trigger.trigger_type === "cron";
  // The path is the part that is true everywhere: the reachable host is the
  // API's ingress, which this app cannot know (`API_URL` is the in-cluster
  // address). Use the server's own value when it ever sends one.
  const webhookEndpoint =
    (trigger as { webhook_url?: string | null }).webhook_url ??
    (trigger.webhook_id ? `/webhooks/${trigger.webhook_id}` : null);

  const model: TriggerOverviewModel = {
    triggerId,
    name: trigger.name,
    description: trigger.description,
    iconUrl: entry?.icon_url ?? null,
    sourceName: getTriggerDisplayName(trigger, entry),
    scheduleText: describeTriggerSchedule(trigger),
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
    webhook: isCron
      ? null
      : {
          url: webhookEndpoint,
          methods: trigger.allowed_methods ?? [],
          events: trigger.event_types ?? [],
        },
    failure: {
      consecutive: trigger.consecutive_failures,
      threshold: trigger.failure_threshold,
    },
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
