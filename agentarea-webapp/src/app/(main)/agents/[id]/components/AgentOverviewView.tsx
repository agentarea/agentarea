import { createElement, type ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import {
  Boxes,
  ChevronRight,
  Clock,
  Gauge,
  ListChecks,
  Shield,
  SquareCheckBig,
  Wallet,
  Zap,
} from "lucide-react";
import { formatRelTime } from "@/app/(main)/dashboard/components/relTime";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { CollapsibleGroup } from "@/components/ui/group-header";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { ProviderIcon } from "@/components/ui/provider-icon";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  agentColorVar,
  getAgentIconComponent,
  type AgentColorToken,
} from "@/lib/agent-identity";
import type { TaskResponse } from "@/lib/api";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  getTaskStatusPresentation,
  type StatusPresentation,
} from "@/lib/status";
import type { PolicyEffect } from "@/types/policies";
import { isRunningTask } from "../../shared/taskStatus";
import { HeroDescription } from "./HeroDescription";
import {
  EmptyRow,
  SectionCard,
  SectionCardHead,
  Stat,
  StatStrip,
} from "./OverviewCard";

/**
 * Everything the overview needs to render, already resolved by the data
 * container ({@link AgentOverview}). Keeping the view free of fetching makes
 * it renderable with fixtures.
 */
export type AgentOverviewModel = {
  agentRef: string;
  name: string;
  description?: string | null;
  colorToken: AgentColorToken;
  iconKey: string;
  status: StatusPresentation;
  model: {
    label: string | null;
    provider: string | null;
    iconUrl: string | null;
  };
  triggers: { count: number; titles: string[] };
  lastActivityAt: string | null;
  stats: {
    /** Terminal runs over the last 7 days. */
    completed7d: number;
    failed7d: number;
    /** Average completed tasks per day, this week vs the previous one. */
    throughput7d: number;
    throughputPrev: number;
    /** Highest single-day completed count in the window (bar scale). */
    maxDaily: number;
    costMtd: number;
    cap: number | null;
    doneToday: number;
    failedToday: number;
  };
  runningTasks: TaskResponse[];
  recentTasks: TaskResponse[];
  pendingApprovals: TaskResponse[];
  skills: string[];
  connections: string[];
  policyCount: number;
  effectCounts: Partial<Record<PolicyEffect, number>>;
};

const fmtUsd = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

type Translator = Awaited<ReturnType<typeof getTranslations>>;

// "2h ago" / "just now" — the compact unit comes from the shared dashboard
// helper, the suffix from this page's catalog.
function agoText(iso: string | null | undefined, t: Translator): string {
  const rel = formatRelTime(iso ?? null, t);
  if (!iso || rel === t("relJustNow")) return rel;
  return t("agoFmt", { time: rel });
}

// Keep semantic color on the tiny marker only. The label stays neutral so the
// guardrail summary does not turn into a second, competing palette.
const EFFECT_MARKER_COLOR: Record<PolicyEffect, string> = {
  deny: "var(--status-danger)",
  approval: "var(--status-warning)",
  cap: "hsl(var(--primary))",
  allow: "hsl(var(--muted-foreground) / 0.72)",
  safety: "hsl(var(--muted-foreground) / 0.72)",
};
const EFFECT_ORDER: PolicyEffect[] = [
  "deny",
  "approval",
  "cap",
  "allow",
  "safety",
];
const EFFECT_KEY: Record<PolicyEffect, string> = {
  deny: "effectDeny",
  approval: "effectApproval",
  cap: "effectCap",
  allow: "effectAllow",
  safety: "effectSafety",
};

export async function AgentOverviewView({
  model,
}: {
  model: AgentOverviewModel;
}) {
  const t = await getTranslations("AgentOverviewPage");
  const { agentRef, stats } = model;

  const totalRuns = stats.completed7d + stats.failed7d;
  const reliability = totalRuns > 0 ? (stats.completed7d / totalRuns) * 100 : 0;
  const throughputDiff = stats.throughput7d - stats.throughputPrev;

  const capPct =
    stats.cap && stats.cap > 0
      ? Math.min(100, (stats.costMtd / stats.cap) * 100)
      : null;
  const HeroIcon = getAgentIconComponent(model.iconKey);
  const triggerText =
    model.triggers.titles.length > 0 && model.triggers.titles.length <= 3
      ? model.triggers.titles.join(" + ")
      : t("triggersCount", { count: model.triggers.count });

  const lastActive = formatRelTime(model.lastActivityAt, t);
  const lastActiveHasAgo =
    Boolean(model.lastActivityAt) && lastActive !== t("relJustNow");

  const settingsHref = `/agents/${agentRef}/settings`;

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
            <EntityAvatar
              size={34}
              rounded={5}
              color={agentColorVar(model.colorToken)}
              icon={createElement(HeroIcon, { strokeWidth: 1.9 })}
              className="mt-0.5"
            />

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="m-0 text-[18px] font-semibold tracking-[-0.022em] md:text-[18px]">
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
                {model.model.label && (
                  <HeroMeta
                    icon={
                      <span className="grid h-[18px] w-[18px] place-items-center rounded-[3px] bg-muted">
                        {model.model.iconUrl ? (
                          <ProviderIcon
                            iconUrl={model.model.iconUrl}
                            name={model.model.provider || model.model.label}
                            size="sm"
                            className="h-3.5 w-3.5"
                          />
                        ) : (
                          <Boxes className="h-3 w-3 text-foreground" />
                        )}
                      </span>
                    }
                  >
                    <b className="font-medium text-foreground/80">
                      {model.model.label}
                    </b>
                    {model.model.provider && <> · {model.model.provider}</>}
                  </HeroMeta>
                )}
                {model.triggers.count > 0 && (
                  <HeroMeta icon={<Zap />}>{triggerText}</HeroMeta>
                )}
                <HeroMeta icon={<Clock />}>
                  {t("lastActive")}{" "}
                  <b className="font-medium text-foreground/80">{lastActive}</b>
                  {lastActiveHasAgo && <> {t("ago")}</>}
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
            icon={<Shield />}
            label={t("reliability")}
            value={totalRuns > 0 ? reliability.toFixed(0) : "—"}
            unit={totalRuns > 0 ? t("successUnit") : undefined}
            bar={totalRuns > 0 ? { pct: reliability } : null}
            sub={
              totalRuns > 0
                ? t("ofTasks", {
                    completed: stats.completed7d,
                    total: totalRuns,
                  })
                : t("noRuns7d")
            }
          />
          <Stat
            icon={<Gauge />}
            label={t("throughput")}
            value={stats.throughput7d.toFixed(1)}
            unit={t("perDay")}
            bar={{
              pct: (stats.throughput7d / Math.max(stats.maxDaily, 1)) * 100,
            }}
            sub={
              stats.throughput7d > 0 || stats.throughputPrev > 0
                ? t("vsLastWeek", {
                    delta: `${throughputDiff >= 0 ? "+" : ""}${throughputDiff.toFixed(1)}`,
                  })
                : t("noThroughput")
            }
            subTone={throughputDiff > 0 ? "up" : "muted"}
          />
          <Stat
            icon={<Wallet />}
            label={t("spendMonth")}
            value={fmtUsd(stats.costMtd)}
            bar={capPct != null ? { pct: capPct } : null}
            sub={
              stats.cap ? t("ofCap", { cap: fmtUsd(stats.cap) }) : t("noCap")
            }
          />
          <Stat
            icon={<SquareCheckBig />}
            label={t("today")}
            value={stats.doneToday}
            unit={t("todayUnit", { failed: stats.failedToday })}
            bar={null}
            sub={t("runningNow", { count: model.runningTasks.length })}
          />
        </StatStrip>

        {/* ===== two-column body ===== */}
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          {/* left: tasks */}
          <SectionCard className="[&>a:last-child>div]:border-b-0">
            <SectionCardHead
              icon={<ListChecks />}
              title={t("tasks")}
              link={{ label: t("allTasks"), href: `/agents/${agentRef}/tasks` }}
            />
            <CollapsibleGroup
              label={t("running")}
              count={model.runningTasks.length}
              color="hsl(var(--primary))"
              sticky={false}
              headerClassName="h-[30px] px-[15px]"
            >
              {model.runningTasks.length === 0 ? (
                <EmptyRow text={t("nothingRunning")} />
              ) : (
                model.runningTasks.map((task) => (
                  <TaskRow key={task.id} task={task} t={t} hideRunningStatus />
                ))
              )}
            </CollapsibleGroup>
            <CollapsibleGroup
              label={t("recent")}
              count={model.recentTasks.length}
              color="hsl(var(--muted-foreground) / 0.6)"
              sticky={false}
              headerClassName="h-[30px] px-[15px]"
            >
              {model.recentTasks.length === 0 ? (
                <EmptyRow
                  text={t("noTasksYet")}
                  action={{
                    label: t("startOne"),
                    href: `/agents/${agentRef}/new-task`,
                  }}
                />
              ) : (
                model.recentTasks.map((task) => (
                  <TaskRow key={task.id} task={task} t={t} />
                ))
              )}
            </CollapsibleGroup>
          </SectionCard>

          {/* right rail */}
          <div className="flex min-w-0 flex-col gap-4">
            {/* configuration: model · skills · connections */}
            <SectionCard className="[&>a:last-child>div]:border-b-0">
              <SectionCardHead
                icon={<Boxes />}
                title={t("configurations")}
                link={{ label: t("configure"), href: settingsHref }}
              />
              <GlanceRow
                href={settingsHref}
                tile={
                  <span className="grid h-7 w-7 place-items-center rounded bg-muted text-foreground">
                    {model.model.iconUrl ? (
                      <ProviderIcon
                        iconUrl={model.model.iconUrl}
                        name={model.model.provider || model.model.label || ""}
                        size="sm"
                      />
                    ) : (
                      <Boxes className="h-[15px] w-[15px]" strokeWidth={1.8} />
                    )}
                  </span>
                }
                title={model.model.label || t("noModel")}
                sub={model.model.provider || t("modelLabel")}
              />
              <GlanceRow
                href={settingsHref}
                tile={<SoftTile icon={<ENTITY_ICONS.skill />} />}
                title={t("skills")}
                sub={
                  model.skills.length > 0
                    ? summarize(model.skills, 2, t)
                    : t("noneGranted")
                }
                count={model.skills.length}
              />
              <GlanceRow
                href={settingsHref}
                tile={<SoftTile icon={<ENTITY_ICONS.client />} />}
                title={t("connections")}
                sub={
                  model.connections.length > 0
                    ? summarize(model.connections, 3, t)
                    : t("noneConnected")
                }
                count={model.connections.length}
              />
            </SectionCard>

            {/* guardrails: budget · approvals · policies */}
            <SectionCard className="[&>a:last-child>div]:border-b-0">
              <SectionCardHead
                icon={<Shield />}
                title={t("guardrails")}
                link={{ label: t("policies"), href: "/policies" }}
              />
              <div className="border-b border-border/60 px-[15px] py-3">
                <div className="mb-2 flex items-baseline justify-between gap-3">
                  <span className="text-[12px] font-medium text-foreground/80">
                    {t("spendThisMonth")}
                  </span>
                  <span className="text-[11.5px] text-muted-foreground">
                    <b className="font-semibold text-foreground tabular-nums">
                      {fmtUsd(stats.costMtd)}
                    </b>
                    {stats.cap ? ` / ${fmtUsd(stats.cap)}` : ""}
                  </span>
                </div>
                {capPct != null ? (
                  <div className="h-1.5 overflow-hidden rounded-[2px] bg-muted">
                    <span
                      className="block h-full rounded-[2px] bg-foreground"
                      style={{ width: `${capPct}%` }}
                    />
                  </div>
                ) : (
                  <p className="text-[11px] text-muted-foreground">
                    {t("noCapConfigured")}
                  </p>
                )}
              </div>

              <GlanceRow
                href={`/agents/${agentRef}/tasks?status=input_required`}
                tile={
                  <EntityAvatar
                    variant="soft"
                    size={28}
                    rounded={4}
                    lines={false}
                    color={
                      model.pendingApprovals.length > 0
                        ? "var(--status-warning)"
                        : "hsl(var(--muted-foreground))"
                    }
                    icon={<Clock strokeWidth={1.8} />}
                  />
                }
                title={t("approvalsPending")}
                sub={
                  model.pendingApprovals.length > 0
                    ? summarize(
                        model.pendingApprovals.map(
                          (task) => task.description || task.id
                        ),
                        2,
                        t,
                        " · "
                      )
                    : t("nonePending")
                }
                trailing={
                  model.pendingApprovals.length > 0 ? (
                    <span
                      className="rounded-[2px] px-[7px] py-px text-[11px] font-bold tabular-nums"
                      style={{
                        color: "var(--status-warning)",
                        background:
                          "color-mix(in srgb, var(--status-warning) 14%, transparent)",
                      }}
                    >
                      {model.pendingApprovals.length}
                    </span>
                  ) : undefined
                }
                chevron={false}
              />

              <GlanceRow
                href="/policies"
                tile={<SoftTile icon={<Shield />} />}
                title={
                  model.policyCount > 0
                    ? t("effectiveGuardrails", { count: model.policyCount })
                    : t("noGuardrails")
                }
                sub={
                  model.policyCount > 0 ? (
                    <span className="flex flex-wrap gap-x-2.5">
                      {EFFECT_ORDER.filter((e) => model.effectCounts[e]).map(
                        (e) => (
                          <span
                            key={e}
                            className="font-medium text-foreground/70"
                          >
                            <span
                              aria-hidden
                              className="mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle"
                              style={{
                                backgroundColor: EFFECT_MARKER_COLOR[e],
                              }}
                            />
                            {t(EFFECT_KEY[e], {
                              count: model.effectCounts[e] ?? 0,
                            })}
                          </span>
                        )
                      )}
                    </span>
                  ) : (
                    t("waitingOnInput")
                  )
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

function HeroMeta({
  icon,
  children,
}: {
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap before:mx-3 before:h-1 before:w-1 before:shrink-0 before:rounded-full before:bg-muted-foreground/40 before:content-[''] first:before:hidden [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:text-muted-foreground/70">
      {icon}
      <span>{children}</span>
    </span>
  );
}

/** Muted 28px icon tile for the glance rail rows. */
function SoftTile({ icon }: { icon: ReactNode }) {
  return (
    <span className="grid h-7 w-7 shrink-0 place-items-center rounded bg-muted text-foreground/80 [&>svg]:h-[15px] [&>svg]:w-[15px]">
      {icon}
    </span>
  );
}

/** "a, b +3" — the first `max` names and a count of the rest. */
function summarize(
  names: string[],
  max: number,
  t: Translator,
  sep = ", "
): string {
  const shown = names.slice(0, max).join(sep);
  const rest = names.length - max;
  return rest > 0 ? `${shown} ${t("more", { count: rest })}` : shown;
}

function TaskRow({
  task,
  t,
  hideRunningStatus = false,
}: {
  task: TaskResponse;
  t: Translator;
  hideRunningStatus?: boolean;
}) {
  const status = String(task.status ?? "unknown");
  const presentation = getTaskStatusPresentation(status);
  const visuallyHideStatus =
    hideRunningStatus && presentation.labelKey === "running";
  const resultCost =
    task.result && typeof task.result === "object"
      ? task.result.total_cost
      : undefined;
  const cost = Number(task.total_cost ?? resultCost ?? 0);
  const when = agoText(task.created_at, t);
  const title = task.description || task.id;
  const sub = isRunningTask(task)
    ? t("started", { time: when })
    : `${presentation.label} · ${when}`;

  return (
    <Link href={`/tasks/${task.id}`} className="block">
      <InteractiveListRow
        className="px-[15px] py-[11px]"
        dividerClassName="border-b border-border/60"
        contentClassName="gap-3"
        end={
          <span className="w-[46px] text-right text-[11.5px] text-muted-foreground tabular-nums">
            {cost > 0 ? fmtUsd(cost) : "—"}
          </span>
        }
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-medium">{title}</div>
          <div className="mt-px truncate text-[11px] text-muted-foreground/80">
            {sub}
          </div>
        </div>
        {visuallyHideStatus ? (
          <span className="sr-only">{presentation.label}</span>
        ) : (
          <StatusIndicator
            size="sm"
            tone={presentation.tone}
            pulse={presentation.pulse}
            className="shrink-0 whitespace-nowrap text-[12px] font-medium"
          >
            {presentation.label}
          </StatusIndicator>
        )}
      </InteractiveListRow>
    </Link>
  );
}

function GlanceRow({
  href,
  tile,
  title,
  sub,
  count,
  trailing,
  chevron = true,
}: {
  href: string;
  tile: ReactNode;
  title: ReactNode;
  sub: ReactNode;
  count?: number;
  trailing?: ReactNode;
  chevron?: boolean;
}) {
  return (
    <Link href={href} className="block">
      <InteractiveListRow
        showIndicator={false}
        className="px-[15px] py-[11px]"
        dividerClassName="border-b border-border/60"
        start={tile}
        end={
          <span className="flex items-center gap-[7px] text-[12px] text-muted-foreground">
            {trailing}
            {count != null && (
              <b className="font-semibold text-foreground/80 tabular-nums">
                {count}
              </b>
            )}
            {chevron && (
              <ChevronRight
                className="h-3.5 w-3.5 text-muted-foreground/60"
                strokeWidth={2}
              />
            )}
          </span>
        }
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-medium">{title}</div>
          <div className="mt-px truncate text-[11px] text-muted-foreground/80">
            {sub}
          </div>
        </div>
      </InteractiveListRow>
    </Link>
  );
}
