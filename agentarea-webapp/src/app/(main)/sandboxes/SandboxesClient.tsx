"use client";

import { useEffect, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { formatDistanceToNowStrict } from "date-fns";
import { Boxes, Cpu, HardDrive, ShieldCheck } from "lucide-react";
import type {
  SandboxListResponse,
  SandboxSummary,
} from "@/api/client/types.gen";
import EmptyState from "@/components/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { listSandboxesAction } from "./actions";

const POLL_INTERVAL_MS = 10_000;

function relativeTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return formatDistanceToNowStrict(date, { addSuffix: true });
}

function stateTone(state: string) {
  switch (state.toLowerCase()) {
    case "running":
      return "success" as const;
    case "pending":
    case "pausing":
    case "stopping":
      return "warning" as const;
    case "failed":
      return "danger" as const;
    case "paused":
      return "info" as const;
    default:
      return "neutral" as const;
  }
}

function SandboxState({ state }: { state: string }) {
  return (
    <StatusIndicator
      tone={stateTone(state)}
      pulse={state.toLowerCase() === "running"}
    >
      {state}
    </StatusIndicator>
  );
}

export default function SandboxesClient({
  initialData,
  initialError,
  searchParams,
}: {
  initialData: SandboxListResponse | null;
  initialError: string | null;
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const t = useTranslations("SandboxesPage");
  const [inventory, setInventory] = useState(initialData);
  const [error, setError] = useState(initialError);
  const [, startTransition] = useTransition();

  useEffect(() => {
    const refresh = () => {
      startTransition(async () => {
        const result = await listSandboxesAction();
        if (result.data) {
          setInventory(result.data);
          setError(null);
        } else {
          setError(result.error);
        }
      });
    };
    const interval = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  if (error && !inventory) {
    return (
      <div className="p-6">
        <EmptyState
          title={t("unavailableTitle")}
          description={t("unavailableDescription")}
          icons={[Boxes, ShieldCheck, HardDrive]}
        />
      </div>
    );
  }

  const sandboxes = inventory?.items ?? [];
  const columns = [
    {
      header: t("state"),
      accessor: "state",
      render: (value: unknown) => <SandboxState state={String(value)} />,
    },
    {
      header: t("sandbox"),
      accessor: "id",
      render: (value: unknown) => (
        <span className="font-mono text-xs">{String(value)}</span>
      ),
    },
    {
      header: t("task"),
      accessor: "task_id",
      render: (value: unknown) => (
        <span className="font-mono text-xs">{String(value)}</span>
      ),
    },
    { header: t("provider"), accessor: "provider" },
    {
      header: t("age"),
      accessor: "created_at",
      render: (value: unknown) => relativeTime(String(value)),
    },
    {
      header: t("expires"),
      accessor: "expires_at",
      render: (value: unknown) =>
        relativeTime(typeof value === "string" ? value : null),
    },
    {
      header: t("resources"),
      accessor: "resources",
      render: (_value: unknown, item?: SandboxSummary) =>
        item ? `${item.resources.cpu} / ${item.resources.memory}` : "—",
    },
    {
      header: t("isolation"),
      accessor: "isolation",
      render: (value: unknown) => (
        <Badge variant="outline">{String(value)}</Badge>
      ),
    },
  ];

  return (
    <div className="p-6">
      {error && (
        <p className="mb-3 text-xs text-amber-600 dark:text-amber-400">
          {t("staleWarning")}
        </p>
      )}
      <GridAndTableViews
        searchParams={searchParams}
        routeChange="/sandboxes"
        data={sandboxes}
        columns={columns}
        itemLink={(sandbox) => `/tasks/${sandbox.task_id}`}
        leftComponent={
          <Badge variant="secondary">
            {t("activeCount", { count: sandboxes.length })}
          </Badge>
        }
        emptyState={
          <EmptyState
            title={t("emptyTitle")}
            description={t("emptyDescription")}
            icons={[Boxes, Cpu, ShieldCheck]}
          />
        }
        cardContent={(sandbox) => (
          <div className="flex flex-col gap-3">
            <div className="flex items-start justify-between gap-2">
              <span className="truncate font-mono text-xs">{sandbox.id}</span>
              <SandboxState state={sandbox.state} />
            </div>
            <div className="text-xs text-muted-foreground">
              {t("task")}: <span className="font-mono">{sandbox.task_id}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="secondary">{sandbox.provider}</Badge>
              <Badge variant="outline">{sandbox.isolation}</Badge>
              <Badge variant="outline">
                {sandbox.resources.cpu} / {sandbox.resources.memory}
              </Badge>
            </div>
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{relativeTime(sandbox.created_at)}</span>
              <span>{relativeTime(sandbox.expires_at)}</span>
            </div>
          </div>
        )}
      />
    </div>
  );
}
