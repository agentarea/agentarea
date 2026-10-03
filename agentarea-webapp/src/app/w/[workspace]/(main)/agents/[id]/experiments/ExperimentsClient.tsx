"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Gauge, Loader2, Play, Square, Upload } from "lucide-react";
import type {
  ArmResponse,
  EvalRunResponse,
  ExperimentResponse,
  RevisionResponse,
} from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Switch } from "@/components/ui/switch";
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
import { candidateGate, percent, usd } from "@/lib/evals";
import { getExperimentStatusPresentation } from "@/lib/status";
import {
  evaluateExperimentAction,
  promoteExperimentAction,
  startExperimentAction,
  stopExperimentAction,
} from "../../shared/evalActions";

type DecisionAction =
  | "start"
  | "ramp"
  | "stop"
  | "promote"
  | "recommend_promote"
  | "continue";

type Decision = {
  at: string;
  action: string;
  reason?: string;
  exposure?: number | null;
  p_regression?: number | null;
  p_better?: number | null;
};

function ArmBlock({ title, arm }: { title: string; arm: ArmResponse }) {
  const t = useTranslations("AgentEvals.experiments");
  return (
    <div className="space-y-1 rounded-md border p-3">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-[11px] text-muted-foreground">{t("runs")}</dt>
          <dd className="tabular-nums">{arm.runs}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-muted-foreground">
            {t("failureRate")}
          </dt>
          <dd className="tabular-nums">{percent(arm.failure_rate, 1)}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-muted-foreground">{t("meanCost")}</dt>
          <dd className="tabular-nums">
            {arm.mean_cost === null || arm.mean_cost === undefined
              ? "—"
              : usd(arm.mean_cost)}
          </dd>
        </div>
      </dl>
    </div>
  );
}

export default function ExperimentsClient({
  agentId,
  agentRef,
  experiments,
  revisions,
  evalRuns,
  initialCandidate,
}: {
  agentId: string;
  agentRef: string;
  experiments: ExperimentResponse[];
  revisions: RevisionResponse[];
  evalRuns: EvalRunResponse[];
  initialCandidate: string | null;
}) {
  const t = useTranslations("AgentEvals");
  const format = useFormatter();
  const router = useWorkspaceRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const numbers = useMemo(
    () => new Map(revisions.map((r) => [r.id, r.number])),
    [revisions]
  );
  const candidates = revisions.filter(
    (r) => r.status === "candidate" && !r.stale
  );
  const running = experiments.find((e) => e.status === "running") ?? null;
  const history = experiments.filter((e) => e.status !== "running");

  const [candidate, setCandidate] = useState(
    initialCandidate && candidates.some((c) => c.id === initialCandidate)
      ? initialCandidate
      : (candidates[0]?.id ?? "")
  );
  const [autoPromote, setAutoPromote] = useState(false);
  const gate = candidate ? candidateGate(evalRuns, candidate) : null;
  const runningGate = running
    ? running.offline_passed
      ? "passed"
      : candidateGate(evalRuns, running.candidate_revision_id)
    : null;
  const [maxDays, setMaxDays] = useState("42");

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => router.refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [running, router]);

  const act = (action: () => Promise<{ ok: boolean; error?: string }>) => {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (!result.ok) setError(result.error ?? null);
      else router.refresh();
    });
  };

  const tActions = useTranslations("AgentEvals.experiments.actions");
  const decisionLabel = (decision: Decision) =>
    tActions(decision.action as DecisionAction, {
      exposure: decision.exposure ?? "",
    });

  const label = (id: string) =>
    t("common.revision", { number: numbers.get(id) ?? "?" });

  return (
    <div className="mx-auto w-full max-w-[1120px] space-y-6 p-6">
      <div className="max-w-2xl space-y-1">
        <h2 className="text-base font-semibold">{t("experiments.title")}</h2>
        <p className="text-sm text-muted-foreground">
          {t("experiments.description")}
        </p>
        <p className="note">{t("experiments.volumeNote")}</p>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {running ? (
        <section className="space-y-4 rounded-lg border p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="flex items-center gap-2 text-sm font-medium">
              <Gauge className="h-4 w-4 text-muted-foreground" />
              {t("experiments.running")}
            </h3>
            <div className="flex items-center gap-2">
              <Button
                size="xs"
                variant="outline"
                disabled={pending}
                onClick={() =>
                  act(() => evaluateExperimentAction(agentId, running.id))
                }
              >
                {pending ? <Loader2 className="animate-spin" /> : <Play />}
                {t("experiments.evaluateNow")}
              </Button>
              <Button
                size="xs"
                variant="outline"
                disabled={pending}
                onClick={() =>
                  act(() => stopExperimentAction(agentId, running.id))
                }
              >
                <Square />
                {t("experiments.stop")}
              </Button>
              <Button
                size="xs"
                disabled={pending}
                onClick={() =>
                  act(() => promoteExperimentAction(agentId, running.id))
                }
              >
                <Upload />
                {t("experiments.promote")}
              </Button>
            </div>
          </div>

          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">
              {t("experiments.traffic")}
            </p>
            <div className="flex h-2.5 w-full justify-end overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-[color:var(--status-info)]"
                style={{ width: `${running.weights.candidate ?? 0}%` }}
              />
            </div>
            <div className="flex justify-between text-xs tabular-nums">
              <span>
                {t("experiments.control", {
                  number: numbers.get(running.control_revision_id) ?? "?",
                })}{" "}
                · {running.weights.control ?? 0}%
              </span>
              <span>
                {t("experiments.candidateArm", {
                  number: numbers.get(running.candidate_revision_id) ?? "?",
                })}{" "}
                · {running.weights.candidate ?? 0}%
              </span>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <ArmBlock
              title={t("experiments.control", {
                number: numbers.get(running.control_revision_id) ?? "?",
              })}
              arm={running.control}
            />
            <ArmBlock
              title={t("experiments.candidateArm", {
                number: numbers.get(running.candidate_revision_id) ?? "?",
              })}
              arm={running.candidate}
            />
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <StatusIndicator
              kind={runningGate === "passed" ? "done" : "attention"}
              size="sm"
            >
              {t(`experiments.offline.${runningGate}`)}
            </StatusIndicator>
            <span className="text-xs text-muted-foreground">
              {running.policy.auto_promote === true
                ? t("experiments.promotesAutomatically")
                : t("experiments.promotionWaits")}
            </span>
          </div>

          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">
              {t("experiments.decisions")}
            </p>
            <ul className="space-y-1 text-sm">
              {[...(running.decisions as Decision[])]
                .reverse()
                .map((decision, index) => (
                  <li
                    key={index}
                    className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5"
                  >
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {format.dateTime(new Date(decision.at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </span>
                    <span className="font-medium">
                      {decisionLabel(decision)}
                    </span>
                    {decision.reason && (
                      <span className="text-xs text-muted-foreground">
                        {decision.reason}
                      </span>
                    )}
                    {decision.p_regression !== undefined &&
                      decision.p_regression !== null && (
                        <span className="text-xs tabular-nums text-muted-foreground">
                          {t("experiments.pRegression")}{" "}
                          {percent(decision.p_regression, 1)} ·{" "}
                          {t("experiments.pBetter")}{" "}
                          {percent(decision.p_better ?? null, 1)}
                        </span>
                      )}
                  </li>
                ))}
            </ul>
          </div>
        </section>
      ) : (
        <section className="space-y-4 rounded-lg border p-4">
          <h3 className="text-sm font-medium">{t("experiments.startTitle")}</h3>
          {candidates.length === 0 ? (
            <p className="note">{t("experiments.noCandidates")}</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <FormLabel>{t("experiments.candidate")}</FormLabel>
                <Select value={candidate} onValueChange={setCandidate}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {candidates.map((r) => (
                      <SelectItem key={r.id} value={r.id}>
                        {t("common.revision", { number: r.number })}
                        {r.message ? ` — ${r.message}` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <FormLabel htmlFor="experiment-days">
                  {t("experiments.maxDuration")}
                </FormLabel>
                <Input
                  id="experiment-days"
                  type="number"
                  min={1}
                  max={90}
                  value={maxDays}
                  onChange={(e) => setMaxDays(e.target.value)}
                />
              </div>
              <label className="flex items-start gap-3 text-sm md:col-span-2">
                <Switch
                  checked={autoPromote}
                  onCheckedChange={setAutoPromote}
                />
                <span>
                  {t("experiments.autoPromote")}
                  <span className="block text-xs text-muted-foreground">
                    {t("experiments.autoPromoteHint")}
                  </span>
                </span>
              </label>
              {gate && (
                <div className="flex flex-wrap items-center gap-2 md:col-span-2">
                  <StatusIndicator
                    kind={gate === "passed" ? "done" : "attention"}
                    size="sm"
                  >
                    {t(`experiments.gate.${gate}`, {
                      number: numbers.get(candidate) ?? "?",
                    })}
                  </StatusIndicator>
                  {gate !== "passed" && (
                    <WorkspaceLink
                      href={`/agents/${agentRef}/evaluations?candidate=${candidate}`}
                      className="text-xs underline underline-offset-2"
                    >
                      {t("versions.evaluate")}
                    </WorkspaceLink>
                  )}
                </div>
              )}
              <div className="md:col-span-2">
                <Button
                  size="sm"
                  disabled={pending || !candidate}
                  onClick={() =>
                    act(() =>
                      startExperimentAction(agentId, {
                        candidate_revision_id: candidate,
                        auto_promote: autoPromote,
                        max_duration_days: Number(maxDays) || null,
                      })
                    )
                  }
                >
                  {pending ? <Loader2 className="animate-spin" /> : <Play />}
                  {t("experiments.start")}
                </Button>
              </div>
            </div>
          )}
        </section>
      )}

      {history.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-medium">{t("experiments.history")}</h3>
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("experiments.candidate")}</TableHead>
                  <TableHead>{t("evaluations.colStatus")}</TableHead>
                  <TableHead>{t("experiments.lastDecision")}</TableHead>
                  <TableHead className="text-right">
                    {t("experiments.runs")}
                  </TableHead>
                  <TableHead>{t("common.created")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.map((experiment) => {
                  const status = getExperimentStatusPresentation(
                    experiment.status,
                    experiment.stop_reason
                  );
                  const last = (experiment.decisions as Decision[]).at(-1);
                  return (
                    <TableRow key={experiment.id}>
                      <TableCell className="font-medium">
                        {label(experiment.candidate_revision_id)}
                      </TableCell>
                      <TableCell>
                        <StatusIndicator kind={status.kind} size="sm">
                          {status.label}
                          {experiment.stop_reason &&
                            ` · ${t(`experiments.stopReasons.${experiment.stop_reason}` as never)}`}
                        </StatusIndicator>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {last ? decisionLabel(last) : "—"}
                      </TableCell>
                      <TableCell className="text-right text-xs tabular-nums">
                        {experiment.control.runs} / {experiment.candidate.runs}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {format.dateTime(new Date(experiment.started_at), {
                          dateStyle: "medium",
                          timeStyle: "short",
                        })}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </section>
      )}
    </div>
  );
}
