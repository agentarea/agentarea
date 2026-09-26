import { getTranslations } from "next-intl/server";
import Link from "@/components/WorkspaceLink";
import {
  Boxes,
  CalendarClock,
  Clock,
  FileText,
  Gauge,
  ListChecks,
  Wallet,
  Webhook,
  Zap,
} from "lucide-react";
import type { TriggerExecutionResponse } from "@/api/client/types.gen";
import { HeroDescription } from "@/components/Overview/HeroDescription";
import {
  EmptyRow,
  FactRow,
  GlanceRow,
  HeroMeta,
  SectionCard,
  SectionCardHead,
  SoftTile,
  Stat,
  StatStrip,
} from "@/components/Overview/OverviewCard";
import { CopyableText } from "@/components/ui/copyable-text";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  getTriggerExecutionStatusPresentation,
  type StatusPresentation,
} from "@/lib/status";
import { cn } from "@/lib/utils";
import type { TaskParameterRef } from "../../components/taskParameters";
import {
  formatCompactDistance,
  formatTriggerCost as fmtUsd,
} from "../../components/triggerDisplay";

/**
 * Everything the trigger overview renders, already resolved by the data
 * container ({@link TriggerOverview}). The view fetches nothing, so it stays
 * renderable with fixtures.
 */
export type TriggerOverviewModel = {
  triggerId: string;
  name: string;
  description?: string | null;
  /** Catalog artwork for the event source; null falls back to the bolt icon. */
  iconUrl: string | null;
  /** Catalog name of the event source, e.g. "Cron", "Telegram". */
  sourceName: string;
  /** Human phrase for when it fires, e.g. "Every day at 9:00 AM". */
  scheduleText: string;
  status: StatusPresentation;
  agent: { id: string; name: string } | null;
  taskText: string;
  skills: TaskParameterRef[];
  mcps: TaskParameterRef[];
  files: string[];
  cron: { expression: string | null; timezone: string | null } | null;
  webhook: { url: string | null; methods: string[]; events: string[] } | null;
  failure: { consecutive: number; threshold: number };
  lastExecutionAt: string | null;
  nextRunTime: string | null;
  metrics: {
    total: number;
    successful: number;
    failed: number;
    /** Percentage, 0-100, as the API reports it. */
    successRate: number;
    avgMs: number;
    /** Spend of the tasks these runs created, over the trigger's history. */
    totalCost: number;
    avgCost: number;
    costedRuns: number;
  } | null;
  executions: TriggerExecutionResponse[];
};

type Translator = Awaited<ReturnType<typeof getTranslations>>;

/**
 * "3m ago" split into the number and its direction, so the stat cell can show
 * "3m" in the mono slot and "ago" as its unit.
 */
function relParts(iso: string | null | undefined) {
  if (!iso) return null;
  const raw = formatCompactDistance(iso);
  if (raw === "—") return null;
  if (raw === "now") return { value: raw, future: null };
  if (raw.startsWith("in ")) return { value: raw.slice(3), future: true };
  return { value: raw.replace(/ ago$/, ""), future: false };
}

function relUnit(
  parts: { future: boolean | null } | null,
  t: Translator
): string | undefined {
  if (!parts || parts.future === null) return undefined;
  return parts.future ? t("fromNow") : t("ago");
}

/** "a, b +3" — the first `max` names and a count of the rest. */
function summarize(names: string[], max: number, t: Translator): string {
  const shown = names.slice(0, max).join(", ");
  const rest = names.length - max;
  return rest > 0 ? `${shown} ${t("andMore", { count: rest })}` : shown;
}

const refNames = (refs: TaskParameterRef[]) =>
  refs.map((ref) => ref.name?.trim() || ref.id);

export async function TriggerOverviewView({
  model,
}: {
  model: TriggerOverviewModel;
}) {
  const t = await getTranslations("TriggersPage.detail");
  const { triggerId, metrics, failure } = model;

  const editHref = `/triggers/${triggerId}/edit`;
  const total = metrics?.total ?? 0;
  const successPct = metrics?.successRate ?? 0;

  const last = relParts(model.lastExecutionAt);
  const next = relParts(model.nextRunTime);
  const lastExecution = model.executions[0];
  const lastStatus = lastExecution
    ? getTriggerExecutionStatusPresentation(lastExecution.status)
    : null;

  const failing = failure.consecutive > 0;

  return (
    <div className="font-inter md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden">
      {/* ===== hero ===== */}
      <header className="relative overflow-hidden border-b border-border bg-gradient-to-b from-muted/30 to-background md:shrink-0">
        <span
          aria-hidden
          className="bg-hatch-soft pointer-events-none absolute inset-y-0 right-0 w-[300px] opacity-[0.35] [-webkit-mask-image:linear-gradient(90deg,transparent,#000_88%)] [mask-image:linear-gradient(90deg,transparent,#000_88%)]"
        />
        <div className="relative w-full px-4 pb-[14px] pt-[13px]">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 grid h-[34px] w-[34px] shrink-0 place-items-center rounded-[5px] border border-border/60 bg-muted/50">
              {model.iconUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={model.iconUrl}
                  alt=""
                  aria-hidden
                  className="h-[19px] w-[19px] shrink-0"
                />
              ) : (
                <Zap
                  className="h-[19px] w-[19px] text-foreground/80"
                  strokeWidth={1.9}
                />
              )}
            </span>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="m-0 text-[18px] font-semibold tracking-[-0.022em]">
                  {model.name}
                </h1>
                <StatusIndicator
                  tone={model.status.tone}
                  pulse={model.status.pulse}
                  className="whitespace-nowrap text-[13px] font-medium"
                >
                  {model.status.label}
                </StatusIndicator>
              </div>

              {model.description && (
                <HeroDescription
                  text={model.description}
                  showMoreLabel={t("showMore")}
                  showLessLabel={t("showLess")}
                />
              )}

              <div className="mt-1.5 flex flex-wrap items-center gap-y-1.5 text-[12px] text-muted-foreground">
                <HeroMeta
                  icon={
                    model.iconUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={model.iconUrl}
                        alt=""
                        aria-hidden
                        className="h-3.5 w-3.5 shrink-0"
                      />
                    ) : (
                      <Zap />
                    )
                  }
                >
                  <b className="font-medium text-foreground/80">
                    {model.scheduleText}
                  </b>
                </HeroMeta>
                {model.agent && (
                  <HeroMeta icon={<ENTITY_ICONS.agent />}>
                    <Link
                      href={`/agents/${model.agent.id}`}
                      className="font-medium text-foreground/80 underline-offset-2 hover:underline"
                    >
                      {model.agent.name}
                    </Link>
                  </HeroMeta>
                )}
                <HeroMeta icon={<Clock />}>
                  {t("lastRun")}{" "}
                  <b className="font-medium text-foreground/80">
                    {last
                      ? last.future === null
                        ? last.value
                        : `${last.value} ${relUnit(last, t)}`
                      : t("never")}
                  </b>
                </HeroMeta>
              </div>
            </div>
          </div>
        </div>
      </header>

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        {/* ===== stat strip ===== */}
        <StatStrip>
          <Stat
            icon={<Gauge />}
            label={t("successRate")}
            value={total > 0 ? successPct.toFixed(0) : "—"}
            unit={total > 0 ? "%" : undefined}
            bar={total > 0 ? { pct: successPct } : null}
            sub={
              failing
                ? t("failureWarning", {
                    count: failure.consecutive,
                    threshold: failure.threshold,
                  })
                : total > 0
                  ? t("ofRuns", {
                      successful: metrics?.successful ?? 0,
                      total,
                    })
                  : t("noRuns")
            }
            subTone={failing ? "down" : "muted"}
          />
          {/* Spend, not a run count: the count is on the Executions tab, and
              what an automation costs is the thing nobody can see today. */}
          <Stat
            icon={<Wallet />}
            label={t("spend")}
            value={fmtUsd(metrics?.totalCost ?? 0)}
            bar={null}
            sub={
              total > 0
                ? t("spendPerRun", { cost: fmtUsd(metrics?.avgCost ?? 0) })
                : t("noRuns")
            }
          />
          <Stat
            icon={<Clock />}
            label={t("lastRun")}
            value={last ? last.value : "—"}
            unit={relUnit(last, t)}
            bar={null}
            sub={lastStatus ? lastStatus.label : t("noExecutions")}
          />
          <Stat
            icon={<CalendarClock />}
            label={t("nextRun")}
            value={next ? next.value : "—"}
            unit={relUnit(next, t)}
            bar={null}
            sub={model.cron ? model.scheduleText : t("noSchedule")}
          />
        </StatStrip>

        {/* ===== two-column body ===== */}
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            {/* the instruction every run carries */}
            <SectionCard>
              <SectionCardHead icon={<FileText />} title={t("task")} />
              {model.taskText.trim() ? (
                <p className="m-0 whitespace-pre-wrap px-[15px] py-3 text-[12.5px] leading-[1.6] text-foreground/90">
                  {model.taskText}
                </p>
              ) : (
                <EmptyRow
                  text={t("taskEmpty")}
                  action={{ label: t("edit"), href: editHref }}
                />
              )}
            </SectionCard>

            <SectionCard className="[&>a:last-child>div]:border-b-0 [&>div:last-child]:border-b-0">
              <SectionCardHead
                icon={<ListChecks />}
                title={t("executions")}
                link={{
                  label: t("allExecutions"),
                  href: `/triggers/${triggerId}/executions`,
                }}
              />
              {model.executions.length === 0 ? (
                <EmptyRow text={t("noExecutions")} />
              ) : (
                model.executions.map((execution) => (
                  <ExecutionRow
                    key={execution.id}
                    execution={execution}
                    t={t}
                  />
                ))
              )}
            </SectionCard>
          </div>

          {/* right rail */}
          <div className="flex min-w-0 flex-col gap-4">
            <SectionCard className="[&>a:last-child>div]:border-b-0">
              <SectionCardHead
                icon={<Boxes />}
                title={t("executionContext")}
                link={{ label: t("edit"), href: editHref }}
              />
              <GlanceRow
                href={model.agent ? `/agents/${model.agent.id}` : editHref}
                tile={<SoftTile icon={<ENTITY_ICONS.agent />} />}
                title={model.agent?.name ?? t("noAgent")}
                sub={t("orchestrator")}
              />
              <GlanceRow
                href={editHref}
                tile={<SoftTile icon={<ENTITY_ICONS.skill />} />}
                title={t("skills")}
                sub={
                  model.skills.length > 0
                    ? summarize(refNames(model.skills), 2, t)
                    : t("noneConfigured")
                }
                count={model.skills.length}
              />
              <GlanceRow
                href={editHref}
                tile={<SoftTile icon={<ENTITY_ICONS.mcp />} />}
                title={t("mcpServers")}
                sub={
                  model.mcps.length > 0
                    ? summarize(refNames(model.mcps), 2, t)
                    : t("noneConfigured")
                }
                count={model.mcps.length}
              />
              <GlanceRow
                href={editHref}
                tile={<SoftTile icon={<FileText />} />}
                title={t("files")}
                sub={
                  model.files.length > 0
                    ? summarize(model.files, 2, t)
                    : t("noneAttached")
                }
                count={model.files.length}
              />
            </SectionCard>

            <SectionCard>
              <SectionCardHead
                icon={model.cron ? <Clock /> : <Webhook />}
                title={t("whenToRun")}
              />
              <FactRow
                title={model.scheduleText}
                sub={model.sourceName}
                trailing={
                  model.cron?.expression ? (
                    <code className="font-mono text-[11px]">
                      {model.cron.expression}
                    </code>
                  ) : undefined
                }
              />
              {model.cron && (
                <FactRow
                  title={t("timezone")}
                  trailing={model.cron.timezone ?? "UTC"}
                />
              )}
              {model.webhook?.url && (
                <div className="space-y-2 border-b border-border/60 px-[15px] py-3 last:border-b-0">
                  <div className="text-[11.5px] text-muted-foreground">
                    {t("webhookUrl")}
                  </div>
                  <CopyableText text={model.webhook.url} />
                </div>
              )}
              {model.webhook && (
                <FactRow
                  title={t("methods")}
                  trailing={
                    <code className="font-mono text-[11px]">
                      {model.webhook.methods.length > 0
                        ? model.webhook.methods.join(" ")
                        : "POST"}
                    </code>
                  }
                />
              )}
              {model.webhook && (
                <FactRow
                  title={t("events")}
                  trailing={
                    model.webhook.events.length > 0
                      ? t("eventsSelected", {
                          count: model.webhook.events.length,
                        })
                      : t("allEvents")
                  }
                />
              )}
              <FactRow
                title={t("failureThreshold")}
                sub={t("failureThresholdHint")}
                trailing={
                  <span className="tabular-nums">
                    {failure.consecutive} / {failure.threshold}
                  </span>
                }
              />
            </SectionCard>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------- subcomponents ------------------------- */

/**
 * One past run. It links to the task it created, which is where the actual
 * work is; a run that produced no task has nowhere to go.
 */
function ExecutionRow({
  execution,
  t,
}: {
  execution: TriggerExecutionResponse;
  t: Translator;
}) {
  const presentation = getTriggerExecutionStatusPresentation(execution.status);
  const when = formatCompactDistance(execution.executed_at);
  const duration =
    execution.execution_time_ms > 0
      ? `${(execution.execution_time_ms / 1000).toFixed(2)}s`
      : null;
  const source = execution.fired_by
    ? t("executionManual")
    : t("executionAutomatic");
  // The error is the whole story when there is one; otherwise the second line
  // carries how the run started and how long it took.
  const sub =
    execution.error_message ||
    [source, duration].filter(Boolean).join(" · ");
  const cost = execution.cost_usd;

  const row = (
    <InteractiveListRow
      showIndicator={false}
      className="px-[15px] py-[11px]"
      dividerClassName="border-b border-border/60"
      contentClassName="gap-3"
      end={
        <span className="flex items-center gap-[10px] text-[12px] text-muted-foreground">
          <span
            className={cn(
              "tabular-nums",
              cost != null && cost > 0 && "font-medium text-foreground/80"
            )}
          >
            {cost != null ? fmtUsd(cost) : "—"}
          </span>
          <StatusIndicator
            size="sm"
            tone={presentation.tone}
            pulse={presentation.pulse}
            className="shrink-0 whitespace-nowrap text-[12px] font-medium"
          >
            {presentation.label}
          </StatusIndicator>
        </span>
      }
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] font-medium">{when}</div>
        <div className="mt-px truncate text-[11px] text-muted-foreground/80">
          {sub}
        </div>
      </div>
    </InteractiveListRow>
  );

  if (!execution.task_id) {
    return <div>{row}</div>;
  }

  return (
    <Link href={`/tasks/${execution.task_id}`} className="block">
      {row}
    </Link>
  );
}
