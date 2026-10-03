"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeft, Loader2, Square } from "lucide-react";
import type { EvalRunDetail, RevisionResponse } from "@/api/client/types.gen";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import WorkspaceLink from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  buildRunMatrix,
  usd,
  type ArmCell,
  type CaseVerdict,
} from "@/lib/evals";
import {
  getEvalRunStatusPresentation,
  getTrialStatusPresentation,
} from "@/lib/status";
import type { StatusKind } from "@/lib/status";
import { stopEvalRunAction } from "../../../../shared/evalActions";

const VERDICT_KIND: Record<CaseVerdict, StatusKind> = {
  regression: "failed",
  improvement: "done",
  pass: "done",
  fail: "failed",
  pending: "running",
};

function ArmTrials({ cell }: { cell: ArmCell }) {
  const t = useTranslations("AgentEvals");
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        {cell.trials.map((trial) => {
          const status = getTrialStatusPresentation(trial.status, trial.passed);
          const glyph = (
            <StatusIndicator
              kind={status.kind}
              aria-label={status.label}
              title={status.label}
            />
          );
          return trial.task_id ? (
            <WorkspaceLink
              key={trial.id}
              href={`/tasks/${trial.task_id}`}
              title={t("evaluations.openTask")}
            >
              {glyph}
            </WorkspaceLink>
          ) : (
            <span key={trial.id}>{glyph}</span>
          );
        })}
        <span className="ml-1 text-xs tabular-nums text-muted-foreground">
          {t("evaluations.passedOfTotal", {
            passed: cell.passed,
            total: cell.total,
          })}
        </span>
      </div>
      {cell.trials
        .filter((trial) => trial.status === "done" || trial.status === "error")
        .slice(0, 1)
        .map((trial) => (
          <ul
            key={trial.id}
            className="space-y-0.5 text-[11px] text-muted-foreground"
          >
            {trial.error && (
              <li className="text-[color:var(--status-danger)]">
                {trial.error}
              </li>
            )}
            {(
              trial.check_results as {
                type: string;
                passed: boolean;
                detail?: string;
              }[]
            )
              .filter((check) => !check.passed)
              .map((check, index) => (
                <li key={index}>
                  {check.type}: {check.detail}
                </li>
              ))}
          </ul>
        ))}
    </div>
  );
}

export default function RunDetailClient({
  agentId,
  agentRef,
  run,
  revisions,
}: {
  agentId: string;
  agentRef: string;
  run: EvalRunDetail;
  revisions: RevisionResponse[];
}) {
  const t = useTranslations("AgentEvals");
  const router = useWorkspaceRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const rows = useMemo(() => buildRunMatrix(run), [run]);
  const numbers = useMemo(
    () => new Map(revisions.map((r) => [r.id, r.number])),
    [revisions]
  );
  const status = getEvalRunStatusPresentation(run.status);
  const active = run.status === "queued" || run.status === "running";
  const summary = run.summary as {
    passed?: boolean;
    regressions?: string[];
    improvements?: string[];
    failing_cases?: string[];
  };
  const passed = summary.passed;
  const improved = summary.improvements?.length ?? 0;
  const verdict = run.candidate_revision_id
    ? passed
      ? t("evaluations.resultPassed")
      : t("evaluations.resultRegressed", {
          count: summary.regressions?.length ?? 0,
        })
    : passed
      ? t("evaluations.resultAllPassed")
      : t("evaluations.resultFailing", {
          count: summary.failing_cases?.length ?? 0,
        });

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => router.refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [active, router]);

  const stop = () => {
    setError(null);
    startTransition(async () => {
      const result = await stopEvalRunAction(agentId, run.id);
      if (!result.ok) setError(result.error);
      else router.refresh();
    });
  };

  return (
    <div className="mx-auto w-full max-w-[1120px] space-y-4 p-6">
      <WorkspaceLink
        href={`/agents/${agentRef}/evaluations`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        {t("evaluations.title")}
      </WorkspaceLink>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="flex items-center gap-3 text-base font-semibold">
            {t("evaluations.detailTitle")}
            <StatusIndicator kind={status.kind}>{status.label}</StatusIndicator>
          </h2>
          <p className="text-sm text-muted-foreground">
            {t("evaluations.baselineArm", {
              number: numbers.get(run.baseline_revision_id) ?? "?",
            })}
            {run.candidate_revision_id &&
              ` · ${t("evaluations.candidateArm", { number: numbers.get(run.candidate_revision_id) ?? "?" })}`}
            {` · ${t("evaluations.trials")}: ${run.trials}`}
            {` · ${usd(run.cost_usd)} / ${usd(run.budget_usd)}`}
          </p>
          {!active && passed !== undefined && (
            <StatusIndicator kind={passed ? "done" : "failed"}>
              {verdict}
              {improved > 0 &&
                ` · ${t("evaluations.resultImproved", { count: improved })}`}
            </StatusIndicator>
          )}
          {run.stop_reason && (
            <p className="text-xs text-muted-foreground">
              {t("evaluations.stopReason", { reason: run.stop_reason })}
            </p>
          )}
        </div>
        {active && (
          <Button size="xs" variant="outline" onClick={stop} disabled={pending}>
            {pending ? <Loader2 className="animate-spin" /> : <Square />}
            {t("evaluations.stop")}
          </Button>
        )}
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("evaluations.case")}</TableHead>
              <TableHead>
                {t("evaluations.baselineArm", {
                  number: numbers.get(run.baseline_revision_id) ?? "?",
                })}
              </TableHead>
              {run.candidate_revision_id && (
                <TableHead>
                  {t("evaluations.candidateArm", {
                    number: numbers.get(run.candidate_revision_id) ?? "?",
                  })}
                </TableHead>
              )}
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.caseId}>
                <TableCell className="max-w-[260px] truncate font-medium">
                  {row.name}
                </TableCell>
                <TableCell>
                  <ArmTrials cell={row.baseline} />
                </TableCell>
                {row.candidate && (
                  <TableCell>
                    <ArmTrials cell={row.candidate} />
                  </TableCell>
                )}
                <TableCell>
                  <StatusIndicator kind={VERDICT_KIND[row.verdict]} size="sm">
                    {t(`evaluations.verdict.${row.verdict}`)}
                  </StatusIndicator>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
