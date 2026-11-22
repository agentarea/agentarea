"use client";

import { useMemo, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Handle,
  NodeResizer,
  Position,
  useReactFlow,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Activity,
  CalendarClock,
  Coins,
  ExternalLink,
  GitFork,
  Inbox,
  Maximize2,
  Network,
  Plus,
  Radio,
  StickyNote,
  Table2,
  UserRound,
  Webhook,
  X,
  type LucideIcon,
} from "lucide-react";
import { TaskConversation } from "@/components/Chat/TaskConversation";
import EntityMark from "@/components/EntityMark";
import McpAppFrame from "@/components/McpAppFrame/McpAppFrame";
import { TaskStatus } from "@/components/TaskStatus";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import WorkspaceLink from "@/components/WorkspaceLink";
import { useCurrency } from "@/hooks/useCurrency";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { formatMoney } from "@/lib/money";
import { getMcpVerificationStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";
import { feedTasks, type OrgSource, type Tile } from "../utils/canvasState";
import type { Happening } from "../utils/liveDiff";
import { agentSpendRows, agentStats, sourceCounts } from "../utils/orgMap";
import { useCanvasTiles } from "./CanvasContext";

export type CanvasNode = Node<Tile>;

// Stable identity: a fresh `{}` on every render would restart the app.
const NO_ARGUMENTS: Record<string, unknown> = {};

const MIN_SIZE = {
  app: { width: 320, height: 220 },
  task: { width: 320, height: 300 },
  feed: { width: 240, height: 160 },
  note: { width: 180, height: 90 },
  table: { width: 360, height: 200 },
  source: { width: 220, height: 120 },
  agent: { width: 220, height: 110 },
  connection: { width: 200, height: 80 },
  activity: { width: 280, height: 240 },
} satisfies Record<Tile["kind"], { width: number; height: number }>;

const SOURCE_ICONS: Record<OrgSource, LucideIcon> = {
  event: ENTITY_ICONS.stream,
  schedule: CalendarClock,
  webhook: Webhook,
  manual: UserRound,
  delegation: GitFork,
  a2a: Network,
};

const HANDLE_SIDES = [
  Position.Top,
  Position.Right,
  Position.Bottom,
  Position.Left,
] as const;

/** Connection points on every side; any of them starts or ends an arrow. */
function TileHandles() {
  return (
    <>
      {HANDLE_SIDES.map((side) => (
        <Handle
          key={side}
          id={side}
          type="source"
          position={side}
          className="!h-2.5 !w-2.5 !border-2 !border-background !bg-primary opacity-0 transition-opacity group-hover:opacity-100"
        />
      ))}
    </>
  );
}

function useMoney() {
  const locale = useLocale();
  const { currency } = useCurrency();
  return (amount: number) => formatMoney(amount, currency, locale);
}

function TileShell({
  tile,
  selected,
  heading,
  href,
  tone = "plain",
  badge,
  children,
}: {
  tile: Tile;
  selected: boolean;
  heading: ReactNode;
  href?: string;
  tone?: "plain" | "note";
  /** What just happened to this tile; drawn over its corner while set. */
  badge?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("CanvasPage");
  const { fitView } = useReactFlow();
  const { removeTile } = useCanvasTiles();
  const min = MIN_SIZE[tile.kind];

  return (
    <div className="group relative h-full w-full">
      <NodeResizer
        isVisible={selected}
        minWidth={min.width}
        minHeight={min.height}
        lineClassName="!border-primary/60"
        handleClassName="!h-2.5 !w-2.5 !rounded-sm !border-primary !bg-background"
      />
      <TileHandles />
      {badge && (
        <span className="pointer-events-none absolute -top-3 right-3 z-10 animate-in fade-in zoom-in rounded-full bg-emerald-600 px-2.5 py-0.5 text-xs font-medium text-white shadow-md">
          {badge}
        </span>
      )}
      <section
        className={cn(
          "flex h-full w-full flex-col overflow-hidden rounded-md border card-shadow",
          tone === "note"
            ? "bg-amber-50 dark:bg-amber-950/40"
            : "bg-white dark:bg-zinc-800",
          selected
            ? "border-primary/60 ring-2 ring-primary/20"
            : badge
              ? "border-emerald-500 ring-4 ring-emerald-500/25"
              : tone === "note"
                ? "border-amber-200 dark:border-amber-900"
                : "border-zinc-200 dark:border-zinc-700"
        )}
      >
        <header
          className={cn(
            "canvas-tile-handle flex shrink-0 cursor-grab items-center gap-1 py-1.5 pl-3 pr-1.5 active:cursor-grabbing",
            tone === "note"
              ? "border-b border-amber-200/70 dark:border-amber-900/70"
              : "border-b border-zinc-200 bg-muted/20 dark:border-zinc-700"
          )}
        >
          <div className="min-w-0 flex-1">{heading}</div>
          <Button
            variant="ghost"
            size="icon"
            className="nodrag h-6 w-6 shrink-0"
            aria-label={t("focus")}
            onClick={() =>
              void fitView({
                nodes: [{ id: tile.id }],
                padding: 0.04,
                duration: 400,
              })
            }
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </Button>
          {href && (
            <Button
              asChild
              variant="ghost"
              size="icon"
              className="nodrag h-6 w-6 shrink-0"
            >
              <WorkspaceLink href={href} aria-label={t("open")}>
                <ExternalLink className="h-3.5 w-3.5" />
              </WorkspaceLink>
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="nodrag h-6 w-6 shrink-0"
            aria-label={t("remove")}
            onClick={() => removeTile(tile.id)}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </header>
        {children}
      </section>
    </div>
  );
}

/**
 * The body of a tile that hosts something with its own pointer handling (an
 * app's iframe, a conversation). Until the tile is selected the canvas owns
 * the pointer — wheel zooms, drag pans; selecting hands it to the content.
 */
function InteractiveBody({
  selected,
  children,
}: {
  selected: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("CanvasPage");
  return (
    <div
      className={cn(
        "relative flex min-h-0 flex-1 flex-col",
        selected && "nodrag nowheel nopan"
      )}
    >
      {children}
      {!selected && (
        <div
          className="absolute inset-0 flex items-end justify-center pb-3 opacity-0 transition-opacity hover:opacity-100"
          aria-hidden
        >
          <span className="rounded-full bg-zinc-900/80 px-3 py-1 text-xs text-white">
            {t("clickToInteract")}
          </span>
        </div>
      )}
    </div>
  );
}

function Unavailable({ message }: { message: string }) {
  return (
    <div className="flex flex-1 items-center justify-center p-4 text-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}

function TileTitle({
  icon,
  title,
  meta,
}: {
  icon: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      {icon}
      <span className="truncate text-sm font-semibold">{title}</span>
      {meta !== undefined && meta !== null && (
        <span className="truncate text-xs text-muted-foreground">{meta}</span>
      )}
    </div>
  );
}

const ICON = "h-4 w-4 shrink-0 text-muted-foreground";

export function AppTile({ data: tile, selected }: NodeProps<CanvasNode>) {
  const t = useTranslations("CanvasPage");
  const { apps } = useCanvasTiles();
  if (tile.kind !== "app") return null;
  const app = apps.get(tile.appId);

  return (
    <TileShell
      tile={tile}
      selected={selected}
      href={
        app
          ? `/apps/${encodeURIComponent(app.instanceId)}/${encodeURIComponent(app.toolName)}`
          : undefined
      }
      heading={
        app ? (
          <TileTitle
            icon={
              <EntityMark
                identity={app.identity}
                className="h-4 w-4 shrink-0 rounded-[3px]"
              />
            }
            title={app.title}
            meta={app.connectionTitle}
          />
        ) : (
          <TileTitle icon={null} title={t("appMissing")} />
        )
      }
    >
      {!app ? (
        <Unavailable message={t("appMissingDescription")} />
      ) : app.resource ? (
        <InteractiveBody selected={selected}>
          <McpAppFrame
            instanceId={app.instanceId}
            toolName={app.toolName}
            title={app.title}
            resource={app.resource}
            entryArguments={NO_ARGUMENTS}
          />
        </InteractiveBody>
      ) : (
        <Unavailable message={`${t("appError")}: ${app.error ?? ""}`} />
      )}
    </TileShell>
  );
}

export function TaskTile({ data: tile, selected }: NodeProps<CanvasNode>) {
  const { tasksById } = useCanvasTiles();
  const known = tile.kind === "task" ? tasksById.get(tile.taskId) : undefined;
  const status = known?.status ?? null;
  const task = useMemo(
    () =>
      tile.kind === "task"
        ? {
            id: tile.taskId,
            agent_id: tile.agentId,
            description: tile.title,
            agent_name: known?.agentName ?? undefined,
            status: status ?? undefined,
            created_at: known?.createdAt,
          }
        : null,
    [tile, known?.agentName, known?.createdAt, status]
  );
  if (tile.kind !== "task" || !task) return null;

  return (
    <TileShell
      tile={tile}
      selected={selected}
      href={`/tasks/${encodeURIComponent(tile.taskId)}`}
      heading={
        <TileTitle
          icon={
            status ? (
              <TaskStatus status={status} caption="never" />
            ) : (
              <Activity className={ICON} />
            )
          }
          title={tile.title}
          meta={known?.agentName}
        />
      }
    >
      <InteractiveBody selected={selected}>
        <TaskConversation task={task} currentStatus={status} />
      </InteractiveBody>
    </TileShell>
  );
}

export function FeedTile({ data: tile, selected }: NodeProps<CanvasNode>) {
  const t = useTranslations("CanvasPage");
  const { tasks, openTask } = useCanvasTiles();
  if (tile.kind !== "feed") return null;
  const rows = feedTasks(tasks, tile.feed);
  const active = tile.feed === "active";

  return (
    <TileShell
      tile={tile}
      selected={selected}
      href={active ? "/tasks" : "/inbox"}
      heading={
        <TileTitle
          icon={
            active ? <Activity className={ICON} /> : <Inbox className={ICON} />
          }
          title={active ? t("feedActive") : t("feedAttention")}
          meta={rows.length > 0 ? rows.length : undefined}
        />
      }
    >
      {rows.length === 0 ? (
        <Unavailable
          message={active ? t("feedEmptyActive") : t("feedEmptyAttention")}
        />
      ) : (
        <ul className="nowheel min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
          {rows.map((task) => (
            <li key={task.id}>
              <button
                type="button"
                title={t("openOnCanvas")}
                className="nodrag flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted/40"
                onClick={() => openTask(task, tile.frame)}
              >
                <TaskStatus
                  status={task.status}
                  caption="never"
                  className="mt-0.5"
                />
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 text-sm">{task.title}</span>
                  {task.agentName && (
                    <span className="block truncate text-xs text-muted-foreground">
                      {task.agentName}
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </TileShell>
  );
}

export function NoteTile({ data: tile, selected }: NodeProps<CanvasNode>) {
  const t = useTranslations("CanvasPage");
  const { setNote } = useCanvasTiles();
  if (tile.kind !== "note") return null;

  return (
    <TileShell
      tile={tile}
      selected={selected}
      tone="note"
      heading={
        <TileTitle icon={<StickyNote className={ICON} />} title={t("note")} />
      }
    >
      <textarea
        value={tile.text}
        placeholder={t("notePlaceholder")}
        onChange={(event) => setNote(tile.id, event.target.value)}
        className="nodrag nowheel min-h-0 flex-1 resize-none bg-transparent px-3 py-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground"
      />
    </TileShell>
  );
}

export function SourceTile({ data: tile, selected }: NodeProps<CanvasNode>) {
  const t = useTranslations("CanvasPage");
  const { tasks, triggers } = useCanvasTiles();
  if (tile.kind !== "source") return null;
  const Icon = SOURCE_ICONS[tile.source];
  const counts = sourceCounts(tasks, triggers, tile.source);
  const named = triggers.filter((trigger) => trigger.source === tile.source);

  return (
    <TileShell
      tile={tile}
      selected={selected}
      href={named.length > 0 ? "/triggers" : "/tasks"}
      heading={
        <TileTitle
          icon={<Icon className={ICON} />}
          title={t(`source.${tile.source}`)}
        />
      }
    >
      <div className="flex min-h-0 flex-1 flex-col gap-2 px-3 py-2">
        <div className="flex gap-4 text-sm">
          <span>
            <span className="font-semibold tabular-nums">{counts.tasks}</span>{" "}
            <span className="text-muted-foreground">{t("statTasks")}</span>
          </span>
          {counts.triggers > 0 && (
            <span>
              <span className="font-semibold tabular-nums">
                {counts.triggers}
              </span>{" "}
              <span className="text-muted-foreground">{t("statTriggers")}</span>
            </span>
          )}
        </div>
        {named.length > 0 && (
          <ul className="nowheel min-h-0 flex-1 space-y-0.5 overflow-y-auto text-xs text-muted-foreground">
            {named.map((trigger) => (
              <li key={trigger.id} className="flex items-center gap-1.5">
                <StatusIndicator
                  size="sm"
                  kind={trigger.active ? "active" : "off"}
                  aria-label={trigger.active ? t("on") : t("off")}
                />
                <span className="truncate">{trigger.name}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </TileShell>
  );
}

export function AgentTile({ data: tile, selected }: NodeProps<CanvasNode>) {
  const t = useTranslations("CanvasPage");
  const money = useMoney();
  const { agents, tasks, triggers, live } = useCanvasTiles();
  if (tile.kind !== "agent") return null;
  const flash = live.flashes.get(tile.agentId);
  const badge = flash
    ? [
        flash.tasks > 0 ? t("flashTasks", { count: flash.tasks }) : null,
        flash.cost > 0 ? `+${money(flash.cost)}` : null,
      ]
        .filter(Boolean)
        .join(" · ") || t("flashEvent")
    : undefined;
  const agent = agents.get(tile.agentId);
  const stats = agentStats(tasks, tile.agentId);
  const triggerCount = triggers.filter(
    (trigger) => trigger.agentId === tile.agentId
  ).length;
  const AgentIcon = ENTITY_ICONS.agent;

  return (
    <TileShell
      tile={tile}
      selected={selected}
      href={`/agents/${encodeURIComponent(tile.agentId)}`}
      badge={badge}
      heading={
        <TileTitle
          icon={<AgentIcon className={ICON} />}
          title={agent?.name ?? t("agentMissing")}
        />
      }
    >
      <div className="flex min-h-0 flex-1 flex-col justify-between gap-2 px-3 py-2 text-sm">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {stats.running > 0 && (
            <StatusIndicator size="sm" kind="running">
              {stats.running}
            </StatusIndicator>
          )}
          {stats.attention > 0 && (
            <StatusIndicator size="sm" kind="attention">
              {stats.attention}
            </StatusIndicator>
          )}
          {stats.done > 0 && (
            <StatusIndicator size="sm" kind="done">
              {stats.done}
            </StatusIndicator>
          )}
          {stats.failed > 0 && (
            <StatusIndicator size="sm" kind="failed">
              {stats.failed}
            </StatusIndicator>
          )}
          {stats.total === 0 && (
            <span className="text-xs text-muted-foreground">
              {t("noRecentTasks")}
            </span>
          )}
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{t("triggerCount", { count: triggerCount })}</span>
          <span className="tabular-nums">{money(stats.cost)}</span>
        </div>
      </div>
    </TileShell>
  );
}

export function ConnectionTile({
  data: tile,
  selected,
}: NodeProps<CanvasNode>) {
  const t = useTranslations("CanvasPage");
  const { connections, agents } = useCanvasTiles();
  if (tile.kind !== "connection") return null;
  const connection = connections.get(tile.connectionId);
  const status = getMcpVerificationStatusPresentation(
    connection?.status ?? "never_attempted"
  );
  const users = [...agents.values()].filter((agent) =>
    agent.connectionIds.includes(tile.connectionId)
  ).length;

  return (
    <TileShell
      tile={tile}
      selected={selected}
      href={`/connections/${encodeURIComponent(tile.connectionId)}`}
      heading={
        connection ? (
          <TileTitle
            icon={
              <EntityMark
                identity={connection.identity}
                className="h-4 w-4 shrink-0 rounded-[3px]"
              />
            }
            title={connection.title}
          />
        ) : (
          <TileTitle icon={null} title={t("connectionMissing")} />
        )
      }
    >
      <div className="flex flex-1 items-center justify-between px-3 text-xs text-muted-foreground">
        <StatusIndicator size="sm" kind={status.kind}>
          {status.label}
        </StatusIndicator>
        <span>{t("usedBy", { count: users })}</span>
      </div>
    </TileShell>
  );
}

const TH = "pb-2 pr-3 font-medium";
const TD = "py-1.5 pr-3";

export function TableTile({ data: tile, selected }: NodeProps<CanvasNode>) {
  const t = useTranslations("CanvasPage");
  const money = useMoney();
  const locale = useLocale();
  const { tasks, agents } = useCanvasTiles();
  if (tile.kind !== "table") return null;
  const when = (iso: string) =>
    new Date(iso).toLocaleString(locale, {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  const agentName = (agentId: string, fallback: string | null) =>
    agents.get(agentId)?.name ?? fallback ?? "—";
  const isTasks = tile.source === "tasks";

  return (
    <TileShell
      tile={tile}
      selected={selected}
      href="/tasks"
      heading={
        <TileTitle
          icon={<Table2 className={ICON} />}
          title={isTasks ? t("tableTasks") : t("tableSpend")}
        />
      }
    >
      <div className="nowheel min-h-0 flex-1 overflow-auto px-3 py-2">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
              {isTasks ? (
                <>
                  <th className={TH}>{t("colTask")}</th>
                  <th className={TH}>{t("colAgent")}</th>
                  <th className={cn(TH, "text-right")}>{t("colCost")}</th>
                  <th className={cn(TH, "text-right")}>{t("colWhen")}</th>
                </>
              ) : (
                <>
                  <th className={TH}>{t("colAgent")}</th>
                  <th className={cn(TH, "text-right")}>{t("colTasks")}</th>
                  <th className={cn(TH, "text-right")}>{t("colCost")}</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {isTasks
              ? tasks.slice(0, 50).map((task) => (
                  <tr
                    key={task.id}
                    className="border-t border-zinc-200 hover:bg-muted/40 dark:border-zinc-700"
                  >
                    <td className={cn(TD, "max-w-[260px]")}>
                      <span className="flex items-center gap-2">
                        <TaskStatus status={task.status} caption="never" />
                        <span className="truncate">{task.title}</span>
                      </span>
                    </td>
                    <td className={cn(TD, "max-w-[160px] truncate")}>
                      {agentName(task.agentId, task.agentName)}
                    </td>
                    <td className={cn(TD, "text-right tabular-nums")}>
                      {task.totalCost ? money(task.totalCost) : "—"}
                    </td>
                    <td
                      className={cn(
                        TD,
                        "whitespace-nowrap text-right text-muted-foreground"
                      )}
                    >
                      {when(task.createdAt)}
                    </td>
                  </tr>
                ))
              : agentSpendRows(tasks).map((row) => (
                  <tr
                    key={row.agentId}
                    className="border-t border-zinc-200 hover:bg-muted/40 dark:border-zinc-700"
                  >
                    <td className={cn(TD, "max-w-[220px] truncate")}>
                      {agentName(row.agentId, row.agentName)}
                    </td>
                    <td className={cn(TD, "text-right tabular-nums")}>
                      {row.tasks}
                    </td>
                    <td className={cn(TD, "text-right tabular-nums")}>
                      {money(row.cost)}
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
    </TileShell>
  );
}

function HappeningLine({ happening }: { happening: Happening }) {
  const t = useTranslations("CanvasPage");
  const money = useMoney();
  const { agents } = useCanvasTiles();
  const name = (agentId: string) => agents.get(agentId)?.name ?? "—";
  switch (happening.kind) {
    case "event":
      return (
        <>
          <Radio className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-600" />
          <span className="min-w-0">
            <span className="font-medium">{t("liveEvent")}</span>{" "}
            <span className="text-muted-foreground">{happening.summary}</span>
            {happening.agentIds.length > 0 && (
              <span className="block text-muted-foreground">
                → {happening.agentIds.map(name).join(", ")}
              </span>
            )}
          </span>
        </>
      );
    case "task":
      return (
        <>
          <Plus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
          <span className="min-w-0">
            <span className="font-medium">{name(happening.agentId)}</span>{" "}
            <span className="text-muted-foreground">
              {t("liveNewTask", { source: t(`source.${happening.source}`) })}
            </span>
            <span className="block truncate">{happening.title}</span>
          </span>
        </>
      );
    case "status":
      return (
        <>
          <TaskStatus
            status={happening.status}
            caption="never"
            className="mt-0.5"
          />
          <span className="min-w-0">
            <span className="font-medium">{name(happening.agentId)}</span>{" "}
            <span className="block truncate text-muted-foreground">
              {happening.title}
            </span>
          </span>
        </>
      );
    case "cost":
      return (
        <>
          <Coins className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
          <span className="min-w-0">
            <span className="font-medium">{name(happening.agentId)}</span>{" "}
            <span className="tabular-nums text-muted-foreground">
              +{money(happening.delta)}
            </span>
          </span>
        </>
      );
  }
}

export function ActivityTile({ data: tile, selected }: NodeProps<CanvasNode>) {
  const t = useTranslations("CanvasPage");
  const { live } = useCanvasTiles();
  if (tile.kind !== "activity") return null;

  return (
    <TileShell
      tile={tile}
      selected={selected}
      href="/events"
      heading={
        <TileTitle
          icon={
            <StatusIndicator
              size="sm"
              kind="running"
              aria-label={t("liveOn")}
            />
          }
          title={t("liveTitle")}
          meta={t("liveOn")}
        />
      }
    >
      {live.happenings.length === 0 ? (
        <Unavailable message={t("liveEmpty")} />
      ) : (
        <ul className="nowheel min-h-0 flex-1 space-y-1 overflow-y-auto p-2 text-xs">
          {live.happenings.map((happening) => (
            <li
              key={happening.id}
              className="flex animate-in fade-in slide-in-from-top-1 items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/40"
            >
              <span className="w-14 shrink-0 tabular-nums text-muted-foreground">
                {new Date(happening.at).toLocaleTimeString(undefined, {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
              <HappeningLine happening={happening} />
            </li>
          ))}
        </ul>
      )}
    </TileShell>
  );
}

export const NODE_TYPES = {
  activity: ActivityTile,
  app: AppTile,
  task: TaskTile,
  feed: FeedTile,
  note: NoteTile,
  table: TableTile,
  source: SourceTile,
  agent: AgentTile,
  connection: ConnectionTile,
};
