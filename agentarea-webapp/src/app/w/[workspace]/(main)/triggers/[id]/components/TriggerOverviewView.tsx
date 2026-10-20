import { getLocale, getTranslations } from "next-intl/server";
import {
  AlertTriangle,
  Boxes,
  CalendarClock,
  Clock,
  FileText,
  Gauge,
  ListChecks,
  Wallet,
} from "lucide-react";
import type {
  TriggerExecutionResponse,
  TriggerResponse,
} from "@/api/client/types.gen";
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
import { OverviewHero } from "@/components/Overview/OverviewHero";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import Link from "@/components/WorkspaceLink";
import { getPricingCurrency } from "@/lib/api-dashboard";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { DEFAULT_SESSION_IDLE_TIMEOUT } from "@/lib/sourceTypes";
import {
  getTriggerExecutionStatusPresentation,
  type StatusPresentation,
} from "@/lib/status";
import { cn } from "@/lib/utils";
import { formatDate } from "@/utils/dateUtils";
import type { TaskParameterRef } from "../../components/taskParameters";
import {
  formatCompactDistance,
  formatTriggerCost,
} from "../../components/triggerDisplay";
import { TriggerStatusBadge } from "../TriggerDetailStatus";

/**
 * Everything the trigger overview renders, already resolved by the data
 * container ({@link TriggerOverview}). The view fetches nothing, so it stays
 * renderable with fixtures.
 */
export type TriggerOverviewModel = {
  triggerId: string;
  name: string;
  description?: string | null;
  /** The trigger's type in the active locale, e.g. "Cron", "Stream". */
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
  /** A stream trigger's session setting; null leaves it to the source's default. */
  session: TriggerResponse["session"];
  /** A stream trigger's batch window; null fires on every event. */
  batch: TriggerResponse["batch"];
  failure: { consecutive: number; threshold: number };
  /** The person who configured it can no longer run its agent; it is stopped. */
  needsOwner: boolean;
  /** Whether this is a stream trigger — decides whether the stream's name is
   * shown (header, "When to run") and how "Next run" reads while idle. */
  isStream: boolean;
  /** The stream whose events fire it, and when that stream last received one. */
  stream: { id: string; name: string | null; lastEventAt: string | null } | null;
  lastExecutionAt: string | null;
  nextRunTime: string | null;
  metrics: {
    total: number;
    successful: number;
    failed: number;
    /** Runs that tried to start a task: the success rate's denominator. */
    attempted: number;
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

/** "{value} {unit}" in the active locale, or just the value for "now". */
function relLabel(
  parts: ReturnType<typeof relParts>,
  t: Translator
): string | null {
  if (!parts) return null;
  if (parts.future === null) return parts.value;
  return `${parts.value} ${relUnit(parts, t)}`;
}

/**
 * `getTriggerExecutionStatusPresentation()` returns an English `label` with
 * no `labelKey` by default; the `executionStatus.*` keys translate it. A
 * status this build doesn't recognise falls back to the raw status string.
 */
function executionStatusLabel(
  presentation: StatusPresentation,
  t: Translator
): string {
  return presentation.labelKey
    ? t(`executionStatus.${presentation.labelKey}`)
    : presentation.label;
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
  const locale = await getLocale();
  // Never guess a currency: a failed lookup threads through as null (see
  // formatMoney in @/lib/money for how that renders) rather than USD.
  const pricingCurrency = await getPricingCurrency();
  const currency = pricingCurrency.ok ? pricingCurrency.currency : null;
  const fmtCost = (value: number) => formatTriggerCost(value, currency, locale);
  const { triggerId, metrics, failure } = model;

  const editHref = `/triggers/${triggerId}/edit`;
  const total = metrics?.total ?? 0;
  const successPct = metrics?.successRate ?? 0;
  const attempted = metrics?.attempted ?? 0;

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
      <OverviewHero
        mark={
          <span className="mt-0.5 grid h-[34px] w-[34px] shrink-0 place-items-center rounded-[5px] border border-border/60 bg-muted/50">
            <SourceGlyph
              cron={Boolean(model.cron)}
              className="h-[19px] w-[19px] text-foreground/80"
            />
          </span>
        }
        title={model.name}
        status={
          <TriggerStatusBadge
            status={model.status}
            className="whitespace-nowrap text-[13px] font-medium"
          />
        }
        description={model.description}
        showMoreLabel={t("showMore")}
        showLessLabel={t("showLess")}
        meta={
          <>
            <HeroMeta icon={<SourceGlyph cron={Boolean(model.cron)} />}>
              <b className="font-medium text-foreground/80">
                {model.scheduleText}
              </b>
            </HeroMeta>
            {model.isStream && model.stream?.name && (
              <HeroMeta icon={<ENTITY_ICONS.stream />}>
                <Link
                  href={`/events/${model.stream.id}`}
                  className="font-medium text-foreground/80 underline-offset-2 hover:underline"
                >
                  {model.stream.name}
                </Link>
              </HeroMeta>
            )}
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
                {relLabel(last, t) ?? t("never")}
              </b>
            </HeroMeta>
          </>
        }
      />


      {model.needsOwner && (
        <div className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 md:shrink-0 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div>
            <div className="font-medium">{t("needsOwnerTitle")}</div>
            <div className="text-xs">{t("needsOwnerBody")}</div>
          </div>
        </div>
      )}

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        {/* ===== stat strip ===== */}
        <StatStrip>
          <Stat
            icon={<Gauge />}
            label={t("successRate")}
            value={attempted > 0 ? successPct.toFixed(0) : "—"}
            unit={attempted > 0 ? "%" : undefined}
            bar={attempted > 0 ? { pct: successPct } : null}
            sub={
              failing
                ? t("failureWarning", {
                    count: failure.consecutive,
                    threshold: failure.threshold,
                  })
                : attempted > 0
                  ? t("ofRuns", {
                      successful: metrics?.successful ?? 0,
                      total: attempted,
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
            value={fmtCost(metrics?.totalCost ?? 0)}
            bar={null}
            sub={
              total > 0
                ? t("spendPerRun", { cost: fmtCost(metrics?.avgCost ?? 0) })
                : t("noRuns")
            }
          />
          <Stat
            icon={<Clock />}
            label={t("lastRun")}
            value={last ? last.value : "—"}
            unit={relUnit(last, t)}
            bar={null}
            sub={
              lastStatus ? (
                <StatusIndicator kind={lastStatus.kind} size="sm">
                  {executionStatusLabel(lastStatus, t)}
                </StatusIndicator>
              ) : (
                t("noExecutions")
              )
            }
          />
          <Stat
            icon={<CalendarClock />}
            label={t("nextRun")}
            value={next ? next.value : "—"}
            unit={relUnit(next, t)}
            bar={null}
            sub={
              model.cron ? model.scheduleText : t("noScheduleStream")
            }
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
                    currency={currency}
                    locale={locale}
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
                icon={<SourceGlyph cron={Boolean(model.cron)} />}
                title={t("whenToRun")}
              />
              <FactRow
                title={model.scheduleText}
                sub={
                  model.isStream && model.stream?.name ? (
                    <Link
                      href={`/events/${model.stream.id}`}
                      className="hover:text-foreground hover:underline"
                    >
                      {model.stream.name}
                    </Link>
                  ) : (
                    model.sourceName
                  )
                }
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
              {model.stream && (
                <FactRow
                  title={t("lastEvent")}
                  trailing={
                    <Link
                      href={`/events/${model.stream.id}`}
                      className="text-primary hover:underline"
                    >
                      {model.stream.lastEventAt
                        ? formatDate(model.stream.lastEventAt, locale)
                        : t("noEventsYet")}
                    </Link>
                  }
                />
              )}
              {model.isStream && (
                <FactRow
                  title={t("session")}
                  sub={
                    model.session?.continue == null
                      ? t("sessionDefault")
                      : model.session.continue
                        ? t("sessionContinues", {
                            timeout:
                              model.session.idle_timeout ??
                              DEFAULT_SESSION_IDLE_TIMEOUT,
                          })
                        : t("sessionEachEvent")
                  }
                />
              )}
              {model.isStream && (
                <FactRow
                  title={t("batch")}
                  sub={
                    !model.batch
                      ? t("batchOff")
                      : model.batch.window && model.batch.max_events
                        ? t("batchWindowOrCount", {
                            window: model.batch.window,
                            count: model.batch.max_events,
                          })
                        : model.batch.window
                          ? t("batchWindow", { window: model.batch.window })
                          : t("batchCount", {
                              count: model.batch.max_events ?? 0,
                            })
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
/** What fires the trigger: the clock, or the stream it listens to. */
function SourceGlyph({
  cron,
  className,
}: {
  cron: boolean;
  className?: string;
}) {
  const Icon = cron ? Clock : ENTITY_ICONS.stream;
  return <Icon aria-hidden className={className} strokeWidth={1.9} />;
}

/**
 * One past run. It links to the task it created, which is where the actual
 * work is; a run that produced no task has nowhere to go.
 */
function ExecutionRow({
  execution,
  t,
  currency,
  locale,
}: {
  execution: TriggerExecutionResponse;
  t: Translator;
  currency: string | null;
  locale: string;
}) {
  const presentation = getTriggerExecutionStatusPresentation(execution.status);
  // relParts/relLabel translate the "ago"/"in" suffix; formatCompactDistance's
  // own return value is raw English and must never reach the screen directly.
  const when = relLabel(relParts(execution.executed_at), t) ?? "—";
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
    execution.error_message || [source, duration].filter(Boolean).join(" · ");
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
            {cost != null ? formatTriggerCost(cost, currency, locale) : "—"}
          </span>
          <StatusIndicator
            size="sm"
            kind={presentation.kind}
            className="shrink-0 whitespace-nowrap text-[12px] font-medium"
          >
            {executionStatusLabel(presentation, t)}
          </StatusIndicator>
        </span>
      }
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] font-medium">{when}</div>
        <div className="mt-px truncate text-[11px] text-muted-foreground">
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
