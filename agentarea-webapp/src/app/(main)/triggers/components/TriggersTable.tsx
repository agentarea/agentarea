"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { Clock, Webhook } from "lucide-react";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";

interface TriggersTableProps {
  triggers: any[];
}

export default function TriggersTable({ triggers }: TriggersTableProps) {
  const router = useRouter();
  const t = useTranslations("TriggersPage.table");
  const tType = useTranslations("TriggersPage.type");
  const tStatus = useTranslations("TriggersPage.status");

  const columns = [
    {
      accessor: "name",
      header: t("name"),
      render: (value: string) => (
        <span className="font-medium text-primary hover:underline">
          {value}
        </span>
      ),
    },
    {
      accessor: "trigger_type",
      header: t("type"),
      render: (value: string) => (
        <Badge variant="outline" className="gap-1">
          {value === "cron" ? (
            <Clock className="h-3 w-3" />
          ) : (
            <Webhook className="h-3 w-3" />
          )}
          {value === "cron" ? tType("cron") : tType("webhook")}
        </Badge>
      ),
    },
    {
      accessor: "agent_name",
      header: t("agent"),
      render: (value: string) => (
        <span className="text-muted-foreground">{value || "-"}</span>
      ),
    },
    {
      accessor: "is_active",
      header: t("status"),
      render: (value: boolean) => (
        <Badge variant={value ? "default" : "secondary"}>
          {value ? tStatus("active") : tStatus("inactive")}
        </Badge>
      ),
    },
    {
      accessor: "next_run_at",
      header: t("nextRun"),
      render: (value: string) => (
        <span className="text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), { addSuffix: true })
            : "-"}
        </span>
      ),
    },
    {
      accessor: "last_run_at",
      header: t("lastRun"),
      render: (value: string) => (
        <span className="text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), { addSuffix: true })
            : "-"}
        </span>
      ),
    },
    {
      accessor: "created_at",
      header: t("created"),
      render: (value: string) => (
        <span className="text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), { addSuffix: true })
            : "-"}
        </span>
      ),
    },
  ];

  return (
    <Table
      data={triggers}
      columns={columns}
      onRowClick={(trigger) => router.push(`/triggers/${trigger.id}`)}
    />
  );
}
