"use client";

import { useTranslations } from "next-intl";
import { AgentLink } from "@/components/AgentIdentity";
import EmptyState from "@/components/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import Link from "@/components/WorkspaceLink";
import type { ExpectedRun } from "../upcoming";
import { RunTriggerButton } from "./RunTriggerButton";

const hrefOf = (r: ExpectedRun) =>
  r.taskId ? `/tasks/${r.taskId}` : `/triggers/${r.triggerId}`;

export function UpcomingTasksContent({ rows }: { rows: ExpectedRun[] }) {
  const t = useTranslations("TasksPage");
  const columns = [
    {
      header: t("expectedWhen"),
      accessor: "firesAt",
      headerClassName: "w-[150px]",
      cellClassName: "whitespace-nowrap",
      render: (value: string) => <TableDateDisplay dateString={value} />,
    },
    {
      header: t("description"),
      accessor: "title",
      rowLink: true,
      render: (title: string) => <span className="font-medium">{title}</span>,
    },
    {
      header: t("agent"),
      accessor: "agentName",
      headerClassName: "hidden md:table-cell",
      cellClassName: "hidden md:table-cell",
      render: (name: string | null, r: ExpectedRun) => (
        <AgentLink agent={{ id: r.agentId, name: name ?? "" }} size="sm" />
      ),
    },
    {
      header: "",
      accessor: "id",
      headerClassName: "w-[160px]",
      render: (_: string, r: ExpectedRun) =>
        r.triggerId && !r.taskId ? (
          <RunTriggerButton triggerId={r.triggerId} />
        ) : (
          <div className="flex justify-end">
            <Link
              href={hrefOf(r)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              {t("open")}
            </Link>
          </div>
        ),
    },
  ];
  return (
    <GridAndTableViews
      viewMode="table"
      data={rows}
      columns={columns}
      rowHref={hrefOf}
      cardContent={(r: ExpectedRun) => (
        <div className="font-medium">{r.title}</div>
      )}
      emptyState={
        <EmptyState
          title={t("expectedEmptyTitle")}
          description={t("expectedEmptyDescription")}
          iconsType="agent"
        />
      }
    />
  );
}
