"use client";

import { useMemo, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import {
  FlaskConical,
  ListChecks,
  Loader2,
  Play,
  Plus,
  Trash2,
} from "lucide-react";
import type {
  CaseResponse,
  EvalRunResponse,
  RevisionResponse,
  SuiteResponse,
} from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import WorkspaceLink from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  CHECK_KINDS,
  checkFromForm,
  checkValue,
  type Check,
  type CheckKind,
} from "@/lib/evals";
import { getEvalRunStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";
import {
  addCaseAction,
  createSuiteAction,
  deleteCaseAction,
  deleteSuiteAction,
  startEvalRunAction,
} from "../../shared/evalActions";

interface Props {
  agentId: string;
  agentRef: string;
  suites: SuiteResponse[];
  casesBySuite: Record<string, CaseResponse[]>;
  runs: EvalRunResponse[];
  revisions: RevisionResponse[];
  initialCandidate: string | null;
  initialSuite: string | null;
}

type Summary = {
  cases?: number;
  baseline?: { cases_passed: number };
  candidate?: { cases_passed: number };
  regressions?: string[];
  passed?: boolean;
};

function useCheckLabel() {
  const t = useTranslations("AgentEvals.evaluations.checkKinds");
  return (kind: string) => t(kind as never);
}

function NewSuiteDialog({ onCreated }: { onCreated: (id: string) => void }) {
  const t = useTranslations("AgentEvals");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const submit = () => {
    setError(null);
    startTransition(async () => {
      const result = await createSuiteAction(name, description);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setOpen(false);
      setName("");
      setDescription("");
      onCreated(result.data.id);
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="xs" variant="outline">
          <Plus />
          {t("evaluations.newSuite")}
        </Button>
      </DialogTrigger>
      <BlueprintDialogContent
        title={t("evaluations.newSuite")}
        actions={
          <Button size="sm" onClick={submit} disabled={pending || !name.trim()}>
            {pending && <Loader2 className="animate-spin" />}
            {t("evaluations.createSuite")}
          </Button>
        }
      >
        <BlueprintFields>
          <div className="space-y-2">
            <FormLabel htmlFor="suite-name">
              {t("evaluations.suiteName")}
            </FormLabel>
            <Input
              id="suite-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <FormLabel htmlFor="suite-description" optional>
              {t("evaluations.suiteDescription")}
            </FormLabel>
            <Textarea
              id="suite-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
            />
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </BlueprintFields>
      </BlueprintDialogContent>
    </Dialog>
  );
}

function AddCaseDialog({
  suiteId,
  onAdded,
}: {
  suiteId: string;
  onAdded: () => void;
}) {
  const t = useTranslations("AgentEvals");
  const checkLabel = useCheckLabel();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [input, setInput] = useState("");
  const [rows, setRows] = useState<{ kind: CheckKind; value: string }[]>([]);
  const [stubs, setStubs] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const submit = () => {
    setError(null);
    let parsedStubs: Record<string, unknown> = {};
    if (stubs.trim()) {
      try {
        const value: unknown = JSON.parse(stubs);
        if (!value || typeof value !== "object" || Array.isArray(value))
          throw new Error();
        parsedStubs = value as Record<string, unknown>;
      } catch {
        setError(t("evaluations.stubsInvalid"));
        return;
      }
    }
    const checks = rows
      .map((row) => checkFromForm(row.kind, row.value))
      .filter((check): check is Check => check !== null);
    startTransition(async () => {
      const result = await addCaseAction(suiteId, {
        name,
        input,
        checks,
        stubs: parsedStubs,
        parameters: {},
      });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setOpen(false);
      setName("");
      setInput("");
      setRows([]);
      setStubs("");
      onAdded();
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="xs" variant="outline">
          <Plus />
          {t("evaluations.addCase")}
        </Button>
      </DialogTrigger>
      <BlueprintDialogContent
        title={t("evaluations.addCase")}
        note={t("evaluations.implicitCheck")}
        actions={
          <Button
            size="sm"
            onClick={submit}
            disabled={pending || !name.trim() || !input.trim()}
          >
            {pending && <Loader2 className="animate-spin" />}
            {t("evaluations.saveCase")}
          </Button>
        }
      >
        <BlueprintFields>
          <div className="space-y-2">
            <FormLabel htmlFor="case-name">
              {t("evaluations.caseName")}
            </FormLabel>
            <Input
              id="case-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <FormLabel htmlFor="case-input">
              {t("evaluations.caseInput")}
            </FormLabel>
            <Textarea
              id="case-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={4}
            />
          </div>
          <div className="space-y-2">
            <FormLabel>{t("evaluations.checks")}</FormLabel>
            {rows.map((row, index) => (
              <div key={index} className="flex items-center gap-2">
                <Select
                  value={row.kind}
                  onValueChange={(kind) =>
                    setRows(
                      rows.map((r, i) =>
                        i === index ? { ...r, kind: kind as CheckKind } : r
                      )
                    )
                  }
                >
                  <SelectTrigger className="w-[210px] shrink-0">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CHECK_KINDS.map((kind) => (
                      <SelectItem key={kind} value={kind}>
                        {checkLabel(kind)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  value={row.value}
                  onChange={(e) =>
                    setRows(
                      rows.map((r, i) =>
                        i === index ? { ...r, value: e.target.value } : r
                      )
                    )
                  }
                />
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t("evaluations.deleteCase")}
                  onClick={() => setRows(rows.filter((_, i) => i !== index))}
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
            <Button
              size="xs"
              variant="ghost"
              onClick={() =>
                setRows([...rows, { kind: "response_contains", value: "" }])
              }
            >
              <Plus />
              {t("evaluations.addCheck")}
            </Button>
          </div>
          <div className="space-y-2">
            <FormLabel htmlFor="case-stubs" optional>
              {t("evaluations.stubs")}
            </FormLabel>
            <Textarea
              id="case-stubs"
              value={stubs}
              onChange={(e) => setStubs(e.target.value)}
              rows={3}
              placeholder='{"mcp__crm__lookup": {"order": "A-1"}}'
              className="font-mono text-xs"
            />
            <p className="note">{t("evaluations.stubsHint")}</p>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </BlueprintFields>
      </BlueprintDialogContent>
    </Dialog>
  );
}

function RunSuiteDialog({
  agentId,
  agentRef,
  suites,
  candidates,
  initialCandidate,
  initialSuite,
}: {
  agentId: string;
  agentRef: string;
  suites: SuiteResponse[];
  candidates: RevisionResponse[];
  initialCandidate: string | null;
  initialSuite: string | null;
}) {
  const t = useTranslations("AgentEvals");
  const router = useWorkspaceRouter();
  const [open, setOpen] = useState(Boolean(initialCandidate));
  const [suiteId, setSuiteId] = useState(initialSuite ?? suites[0]?.id ?? "");
  const [candidate, setCandidate] = useState(initialCandidate ?? "none");
  const [trials, setTrials] = useState("3");
  const [budget, setBudget] = useState("5");
  const [allowSandbox, setAllowSandbox] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const submit = () => {
    setError(null);
    startTransition(async () => {
      const result = await startEvalRunAction(agentId, {
        suite_id: suiteId,
        candidate_revision_id: candidate === "none" ? null : candidate,
        trials: Number(trials),
        budget_usd: budget,
        allow_sandbox: allowSandbox,
      });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setOpen(false);
      router.push(`/agents/${agentRef}/evaluations/runs/${result.data.id}`);
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="xs" disabled={suites.length === 0}>
          <Play />
          {t("evaluations.runSuite")}
        </Button>
      </DialogTrigger>
      <BlueprintDialogContent
        title={t("evaluations.runTitle")}
        description={t("evaluations.runDescription")}
        actions={
          <Button
            size="sm"
            onClick={submit}
            disabled={pending || !suiteId || !(Number(budget) > 0)}
          >
            {pending && <Loader2 className="animate-spin" />}
            {t("evaluations.start")}
          </Button>
        }
      >
        <BlueprintFields>
          <div className="space-y-2">
            <FormLabel>{t("evaluations.suite")}</FormLabel>
            <Select value={suiteId} onValueChange={setSuiteId}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {suites.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name} ({s.case_count})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <FormLabel>{t("evaluations.candidateRevision")}</FormLabel>
            <Select value={candidate} onValueChange={setCandidate}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">
                  {t("evaluations.noCandidate")}
                </SelectItem>
                {candidates.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {t("common.revision", { number: r.number })}
                    {r.message ? ` — ${r.message}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <FormLabel htmlFor="run-trials">
                {t("evaluations.trials")}
              </FormLabel>
              <Input
                id="run-trials"
                type="number"
                min={1}
                max={20}
                value={trials}
                onChange={(e) => setTrials(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <FormLabel htmlFor="run-budget">
                {t("evaluations.budget")}
              </FormLabel>
              <Input
                id="run-budget"
                type="number"
                min={0}
                step="0.5"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
            </div>
          </div>
          <p className="note">{t("evaluations.trialsHint")}</p>
          <label className="flex items-start gap-2 text-sm">
            <Checkbox
              checked={allowSandbox}
              onCheckedChange={(value) => setAllowSandbox(value === true)}
            />
            <span>
              {t("evaluations.allowSandbox")}
              <span className="block text-xs text-muted-foreground">
                {t("evaluations.allowSandboxHint")}
              </span>
            </span>
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </BlueprintFields>
      </BlueprintDialogContent>
    </Dialog>
  );
}

export default function EvaluationsClient({
  agentId,
  agentRef,
  suites,
  casesBySuite,
  runs,
  revisions,
  initialCandidate,
  initialSuite,
}: Props) {
  const t = useTranslations("AgentEvals");
  const checkLabel = useCheckLabel();
  const router = useWorkspaceRouter();
  const [selected, setSelected] = useState<string | null>(
    initialSuite ?? suites[0]?.id ?? null
  );
  const [error, setError] = useState<string | null>(null);
  const [, startTransition] = useTransition();
  const suiteNames = useMemo(
    () => new Map(suites.map((s) => [s.id, s.name])),
    [suites]
  );
  const numbers = useMemo(
    () => new Map(revisions.map((r) => [r.id, r.number])),
    [revisions]
  );
  const candidates = revisions.filter(
    (r) => r.status === "candidate" && !r.stale
  );
  const cases = selected ? (casesBySuite[selected] ?? []) : [];

  const run = (action: () => Promise<{ ok: boolean; error?: string }>) => {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (!result.ok) {
        setError(result.error ?? null);
        return;
      }
      router.refresh();
    });
  };

  return (
    <div className="mx-auto w-full max-w-[1120px] space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl space-y-1">
          <h2 className="text-base font-semibold">{t("evaluations.title")}</h2>
          <p className="text-sm text-muted-foreground">
            {t("evaluations.description")}
          </p>
        </div>
        <RunSuiteDialog
          agentId={agentId}
          agentRef={agentRef}
          suites={suites}
          candidates={candidates}
          initialCandidate={initialCandidate}
          initialSuite={initialSuite}
        />
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <section className="grid gap-4 md:grid-cols-[260px_1fr]">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">{t("evaluations.suites")}</h3>
            <NewSuiteDialog
              onCreated={(id) => {
                setSelected(id);
                router.refresh();
              }}
            />
          </div>
          {suites.length === 0 ? (
            <p className="note">{t("evaluations.noSuites")}</p>
          ) : (
            <ul className="space-y-1">
              {suites.map((suite) => (
                <li key={suite.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(suite.id)}
                    className={cn(
                      "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-muted",
                      selected === suite.id && "bg-muted font-medium"
                    )}
                  >
                    <span className="flex items-center gap-2 truncate">
                      <ListChecks className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">{suite.name}</span>
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {suite.case_count}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-3">
          {selected && (
            <>
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-medium">
                  {t("evaluations.cases")} · {suiteNames.get(selected)}
                </h3>
                <div className="flex items-center gap-2">
                  <AddCaseDialog
                    suiteId={selected}
                    onAdded={() => router.refresh()}
                  />
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() =>
                      run(async () => {
                        const result = await deleteSuiteAction(selected);
                        if (result.ok) setSelected(null);
                        return result;
                      })
                    }
                  >
                    <Trash2 />
                    {t("evaluations.deleteSuite")}
                  </Button>
                </div>
              </div>
              {cases.length === 0 ? (
                <p className="note">{t("evaluations.noCases")}</p>
              ) : (
                <div className="rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("evaluations.caseName")}</TableHead>
                        <TableHead>{t("evaluations.checks")}</TableHead>
                        <TableHead>{t("evaluations.stubs")}</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {cases.map((testCase) => (
                        <TableRow key={testCase.id}>
                          <TableCell className="max-w-[280px]">
                            <p className="truncate font-medium">
                              {testCase.name}
                            </p>
                            <p className="truncate text-xs text-muted-foreground">
                              {testCase.input}
                            </p>
                          </TableCell>
                          <TableCell className="text-xs">
                            {testCase.checks.length === 0
                              ? checkLabel("completed")
                              : testCase.checks.map((check, i) => (
                                  <span key={i} className="block truncate">
                                    {checkLabel(String(check.type))}:{" "}
                                    {checkValue(check as Check)}
                                  </span>
                                ))}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {Object.keys(testCase.stubs).join(", ") || "—"}
                          </TableCell>
                          <TableCell className="text-right">
                            <Button
                              size="icon"
                              variant="ghost"
                              aria-label={t("evaluations.deleteCase")}
                              onClick={() =>
                                run(() =>
                                  deleteCaseAction(selected, testCase.id)
                                )
                              }
                            >
                              <Trash2 />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </>
          )}
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="flex items-center gap-2 text-sm font-medium">
          <FlaskConical className="h-4 w-4 text-muted-foreground" />
          {t("evaluations.runs")}
        </h3>
        {runs.length === 0 ? (
          <p className="note">{t("evaluations.noRuns")}</p>
        ) : (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("evaluations.colSuite")}</TableHead>
                  <TableHead>{t("evaluations.colStatus")}</TableHead>
                  <TableHead>{t("evaluations.colBaseline")}</TableHead>
                  <TableHead>{t("evaluations.colCandidate")}</TableHead>
                  <TableHead>{t("evaluations.colRegressions")}</TableHead>
                  <TableHead className="text-right">
                    {t("evaluations.colCost")}
                  </TableHead>
                  <TableHead>{t("common.created")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((evalRun) => {
                  const summary = evalRun.summary as Summary;
                  const status = getEvalRunStatusPresentation(evalRun.status);
                  const total = summary.cases ?? 0;
                  return (
                    <TableRow
                      key={evalRun.id}
                      className="cursor-pointer"
                      onClick={() =>
                        router.push(
                          `/agents/${agentRef}/evaluations/runs/${evalRun.id}`
                        )
                      }
                    >
                      <TableCell>
                        <WorkspaceLink
                          href={`/agents/${agentRef}/evaluations/runs/${evalRun.id}`}
                          className="font-medium hover:underline"
                        >
                          {suiteNames.get(evalRun.suite_id) ??
                            evalRun.suite_id.slice(0, 8)}
                        </WorkspaceLink>
                      </TableCell>
                      <TableCell>
                        <StatusIndicator kind={status.kind} size="sm">
                          {status.label}
                        </StatusIndicator>
                      </TableCell>
                      <TableCell className="text-xs">
                        {t("common.revision", {
                          number:
                            numbers.get(evalRun.baseline_revision_id) ?? "?",
                        })}
                        {summary.baseline &&
                          ` · ${t("evaluations.passedCases", { passed: summary.baseline.cases_passed, total })}`}
                      </TableCell>
                      <TableCell className="text-xs">
                        {evalRun.candidate_revision_id
                          ? `${t("common.revision", { number: numbers.get(evalRun.candidate_revision_id) ?? "?" })}${
                              summary.candidate
                                ? ` · ${t("evaluations.passedCases", { passed: summary.candidate.cases_passed, total })}`
                                : ""
                            }`
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs">
                        {summary.regressions
                          ? t("evaluations.regressionsCount", {
                              count: summary.regressions.length,
                            })
                          : "—"}
                      </TableCell>
                      <TableCell className="text-right text-xs tabular-nums">
                        ${Number(evalRun.cost_usd).toFixed(2)} / $
                        {Number(evalRun.budget_usd).toFixed(2)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {new Date(evalRun.created_at).toLocaleString()}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}
