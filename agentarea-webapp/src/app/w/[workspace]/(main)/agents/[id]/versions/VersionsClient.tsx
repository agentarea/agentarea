"use client";

import { useMemo, useState, useTransition } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  FileText,
  GitCompare,
  Loader2,
  Plus,
  Undo2,
  Upload,
} from "lucide-react";
import type {
  FieldChange,
  RevisionOutcomeResponse,
  RevisionResponse,
} from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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
import { percent, usd } from "@/lib/evals";
import { getRevisionStatusPresentation } from "@/lib/status";
import {
  activateRevisionAction,
  createCandidateAction,
  diffRevisionAction,
} from "../../shared/evalActions";

interface Props {
  agentId: string;
  agentRef: string;
  instruction: string;
  revisions: RevisionResponse[];
  outcomes: RevisionOutcomeResponse[];
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function NewCandidateDialog({
  agentId,
  instruction,
}: {
  agentId: string;
  instruction: string;
}) {
  const t = useTranslations("AgentEvals");
  const router = useWorkspaceRouter();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(instruction);
  const [message, setMessage] = useState("");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const submit = () => {
    setError(null);
    startTransition(async () => {
      const result = await createCandidateAction(agentId, {
        instruction: text,
        message: message || null,
        rationale: rationale || null,
      });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setOpen(false);
      setMessage("");
      setRationale("");
      router.refresh();
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setText(instruction);
      }}
    >
      <DialogTrigger asChild>
        <Button size="xs">
          <Plus />
          {t("versions.newCandidate")}
        </Button>
      </DialogTrigger>
      <BlueprintDialogContent
        title={t("versions.form.title")}
        description={t("versions.form.description")}
        actions={
          <Button size="sm" onClick={submit} disabled={pending || !text.trim()}>
            {pending && <Loader2 className="animate-spin" />}
            {t("versions.form.submit")}
          </Button>
        }
      >
        <BlueprintFields>
          <div className="space-y-2">
            <FormLabel htmlFor="candidate-instruction" icon={FileText}>
              {t("versions.form.instruction")}
            </FormLabel>
            <Textarea
              id="candidate-instruction"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={10}
            />
          </div>
          <div className="space-y-2">
            <FormLabel htmlFor="candidate-message" optional>
              {t("versions.form.message")}
            </FormLabel>
            <Input
              id="candidate-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={t("versions.form.messagePlaceholder")}
            />
          </div>
          <div className="space-y-2">
            <FormLabel htmlFor="candidate-rationale" optional>
              {t("versions.form.rationale")}
            </FormLabel>
            <Textarea
              id="candidate-rationale"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder={t("versions.form.rationalePlaceholder")}
              rows={3}
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

function DiffDialog({
  agentId,
  revision,
}: {
  agentId: string;
  revision: RevisionResponse;
}) {
  const t = useTranslations("AgentEvals");
  const [changes, setChanges] = useState<FieldChange[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const load = () => {
    setError(null);
    startTransition(async () => {
      const result = await diffRevisionAction(agentId, revision.id);
      if (result.ok) setChanges(result.data);
      else setError(result.error);
    });
  };

  return (
    <Dialog onOpenChange={(open) => open && load()}>
      <DialogTrigger asChild>
        <Button size="xs" variant="ghost">
          <GitCompare />
          {t("versions.diff")}
        </Button>
      </DialogTrigger>
      <BlueprintDialogContent
        title={t("versions.diffTitle", { number: revision.number })}
      >
        <BlueprintFields>
          {pending && <Loader2 className="h-4 w-4 animate-spin" />}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {changes && changes.length === 0 && (
            <p className="note">{t("versions.diffEmpty")}</p>
          )}
          {changes?.map((change) => (
            <div key={change.field} className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">
                {change.field}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {t("versions.diffBefore")}
              </p>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-destructive/5 p-2 text-xs">
                {formatValue(change.before)}
              </pre>
              <p className="text-[11px] text-muted-foreground">
                {t("versions.diffAfter", { number: revision.number })}
              </p>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2 text-xs">
                {formatValue(change.after)}
              </pre>
            </div>
          ))}
        </BlueprintFields>
      </BlueprintDialogContent>
    </Dialog>
  );
}

export default function VersionsClient({
  agentId,
  agentRef,
  instruction,
  revisions,
  outcomes,
}: Props) {
  const t = useTranslations("AgentEvals");
  const format = useFormatter();
  const router = useWorkspaceRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [, startTransition] = useTransition();
  const byRevision = useMemo(
    () => new Map(outcomes.map((o) => [o.revision_id, o])),
    [outcomes]
  );

  const serve = (revision: RevisionResponse) => {
    if (
      !window.confirm(t("versions.confirmServe", { number: revision.number }))
    )
      return;
    setError(null);
    setBusy(revision.id);
    startTransition(async () => {
      const result = await activateRevisionAction(agentId, revision.id);
      setBusy(null);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      router.refresh();
    });
  };

  return (
    <div className="mx-auto w-full max-w-[1120px] space-y-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl space-y-1">
          <h2 className="text-base font-semibold">{t("versions.title")}</h2>
          <p className="text-sm text-muted-foreground">
            {t("versions.description")}
          </p>
        </div>
        <NewCandidateDialog agentId={agentId} instruction={instruction} />
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {revisions.length === 0 ? (
        <p className="note">{t("versions.empty")}</p>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("versions.colVersion")}</TableHead>
                <TableHead>{t("versions.colChange")}</TableHead>
                <TableHead className="text-right">
                  {t("versions.colRuns")}
                </TableHead>
                <TableHead className="text-right">
                  {t("versions.colSuccess")}
                </TableHead>
                <TableHead className="text-right">
                  {t("versions.colMeanCost")}
                </TableHead>
                <TableHead>{t("versions.colCreated")}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {revisions.map((revision) => {
                const outcome = byRevision.get(revision.id);
                const status = getRevisionStatusPresentation(
                  revision.status,
                  revision.stale
                );
                const isCandidate = revision.status === "candidate";
                return (
                  <TableRow key={revision.id}>
                    <TableCell className="whitespace-nowrap font-medium">
                      <div className="flex items-center gap-2">
                        <span>
                          {t("common.revision", { number: revision.number })}
                        </span>
                        <StatusIndicator kind={status.kind} size="sm">
                          {status.label}
                        </StatusIndicator>
                      </div>
                    </TableCell>
                    <TableCell className="max-w-[320px]">
                      <p className="truncate text-sm">
                        {revision.message ||
                          t(`versions.origin.${revision.origin}` as never)}
                      </p>
                      {revision.rationale && (
                        <p className="truncate text-xs text-muted-foreground">
                          {revision.rationale}
                        </p>
                      )}
                      {revision.stale && (
                        <p className="text-xs text-muted-foreground">
                          {t("versions.staleHint")}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {outcome?.runs ?? 0}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {percent(outcome?.success_rate)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {outcome?.mean_cost ? usd(outcome.mean_cost) : "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {format.dateTime(new Date(revision.created_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {!revision.current && (
                          <DiffDialog agentId={agentId} revision={revision} />
                        )}
                        {isCandidate && !revision.stale && (
                          <>
                            <Button size="xs" variant="ghost" asChild>
                              <WorkspaceLink
                                href={`/agents/${agentRef}/evaluations?candidate=${revision.id}`}
                              >
                                {t("versions.evaluate")}
                              </WorkspaceLink>
                            </Button>
                            <Button size="xs" variant="ghost" asChild>
                              <WorkspaceLink
                                href={`/agents/${agentRef}/experiments?candidate=${revision.id}`}
                              >
                                {t("versions.experiment")}
                              </WorkspaceLink>
                            </Button>
                          </>
                        )}
                        {!revision.current && !revision.stale && (
                          <Button
                            size="xs"
                            variant="outline"
                            onClick={() => serve(revision)}
                            disabled={busy === revision.id}
                          >
                            {busy === revision.id ? (
                              <Loader2 className="animate-spin" />
                            ) : isCandidate ? (
                              <Upload />
                            ) : (
                              <Undo2 />
                            )}
                            {isCandidate
                              ? t("versions.serve")
                              : t("versions.rollBack")}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <p className="note">{t("versions.observational")}</p>
    </div>
  );
}
