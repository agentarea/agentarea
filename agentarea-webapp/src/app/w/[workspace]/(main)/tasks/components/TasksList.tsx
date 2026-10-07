"use client";

import { useTranslations } from "next-intl";
import type { TriggerCatalogEntry } from "@/app/w/[workspace]/(main)/triggers/components/triggerDisplay";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { AgentLink } from "@/components/AgentIdentity";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { TaskItem } from "@/components/TaskItem";
import { TaskSourceBadge } from "@/components/TaskSourceBadge";
import { TaskStatus } from "@/components/TaskStatus";
import type { TaskWithAgent } from "@/lib/api";
import { CARD_GRID_WIDE } from "@/lib/collectionGrids";
import TaskCostDisplay, { TaskCostProvider } from "./TaskCostDisplay";

interface TasksListProps {
  initialTasks: TaskWithAgent[];
  viewMode?: string;
  /** Names and draws the channel each task came from. */
  catalog?: TriggerCatalogEntry[];
  /**
   * Principal id -> display name, resolved by the caller via GET /v1/principals:
   * each task's creator, plus any principal its source names. An id missing from
   * the map is one nothing could resolve, and is rendered as unknown rather than
   * as the id.
   */
  principalNames?: Record<string, string>;
  /**
   * Drop the agent column. Set on agent-scoped listings, where every row names
   * the same agent the page is already about.
   */
  showAgent?: boolean;
}

export default function TasksList({
  initialTasks,
  viewMode = "table",
  catalog = [],
  principalNames = {},
  showAgent = true,
}: TasksListProps) {
  const t = useTranslations("TasksPage");

  const taskColumns = [
    {
      accessor: "status",
      header: t("statusLabel"),
      headerClassName: "w-[140px]",
      cellClassName: "w-[140px]",
      render: (value: string, row: TaskWithAgent) => (
        <div className="flex flex-col gap-1">
          <TaskStatus
            status={value}
            size="default"
            caption="auto"
            className="font-medium"
          />
          {row.scheduled_at && (
            <TableDateDisplay dateString={row.scheduled_at} />
          )}
        </div>
      ),
    },
    {
      accessor: "description",
      header: t("description"),
      headerClassName: "w-auto",
      cellClassName: "min-w-0 md:max-w-[460px]",
      rowLink: true,
      render: (value: string) => (
        <p className="line-clamp-2 break-words text-[13px] font-semibold leading-5 text-foreground">
          {value || t("noDescription")}
        </p>
      ),
    },
    ...(showAgent
      ? [
          {
            accessor: "agent_name",
            header: t("agent"),
            headerClassName: "hidden w-[190px] md:table-cell",
            cellClassName: "hidden w-[190px] max-w-[190px] md:table-cell",
            render: (value: string, row: TaskWithAgent) => (
              <AgentLink
                agent={{ id: row.agent_id, name: value || "Unknown Agent" }}
                size="xs"
                nameClassName="text-xs"
              />
            ),
          },
        ]
      : []),
    {
      accessor: "parameters",
      header: t("source"),
      headerClassName: "hidden w-[180px] md:table-cell",
      cellClassName: "hidden w-[180px] max-w-[180px] md:table-cell",
      // One column, not two: where a task came from and who it belongs to are
      // the same question asked of different task kinds. A task nobody
      // automated renders as its person; an automated one keeps its badge and
      // carries the owner in the tooltip.
      render: (value: TaskWithAgent["parameters"], row: TaskWithAgent) => (
        <TaskSourceBadge
          parameters={value}
          createdBy={row.created_by}
          principalNames={principalNames}
          catalog={catalog}
        />
      ),
    },
    {
      accessor: "total_cost",
      header: t("cost"),
      headerClassName: "hidden w-[110px] text-right md:table-cell",
      cellClassName: "hidden text-right md:table-cell",
      render: (value: string | number | null | undefined) => {
        const num = value != null ? Number(value) : null;
        return (
          <div className="font-mono text-xs tabular-nums text-muted-foreground">
            {num != null && !isNaN(num) ? (
              <TaskCostDisplay amount={num} />
            ) : (
              <span>—</span>
            )}
          </div>
        );
      },
    },
    {
      accessor: "created_at",
      header: t("created"),
      headerClassName: "hidden w-[150px] md:table-cell",
      cellClassName: "hidden whitespace-nowrap md:table-cell",
      render: (value: string) => <TableDateDisplay dateString={value} />,
    },
  ];

  return (
    <TaskCostProvider>
      <GridAndTableViews
        viewMode={viewMode}
        data={initialTasks}
        columns={taskColumns}
        rowHref={(task) => `/tasks/${task.id}`}
        wrapCardContent={false}
        gridClassName={CARD_GRID_WIDE}
        emptyState={null}
        cardContent={(task) => (
          <TaskItem task={task} showAgentName={showAgent} />
        )}
      />
    </TaskCostProvider>
  );
}
