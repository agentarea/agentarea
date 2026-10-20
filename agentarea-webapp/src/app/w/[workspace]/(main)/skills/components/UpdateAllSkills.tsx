"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { RefreshCw, X } from "lucide-react";
import type { SkillUpdateResultResponse } from "@/api/client/types.gen";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import Link from "@/components/WorkspaceLink";
import { apiErrorMessage } from "@/lib/api-errors";
import { updateAllSkillsAction } from "@/lib/server-actions";
import { getSkillUpdateResultPresentation } from "@/lib/status";

type UpdateAll =
  | { phase: "idle" }
  | { phase: "running" }
  | { phase: "done"; results: SkillUpdateResultResponse[] }
  | { phase: "failed"; message: string };

/**
 * Update every installed skill with an update and no local edit
 * (POST /skills/update-all). `onDone` refetches the list so the markers clear.
 */
export function useUpdateAllSkills(onDone: () => void) {
  const t = useTranslations("SkillsPage.update");
  const [state, setState] = useState<UpdateAll>({ phase: "idle" });

  const run = async () => {
    setState({ phase: "running" });
    try {
      const result = await updateAllSkillsAction();
      if (result.error || !result.data) {
        setState({
          phase: "failed",
          message: apiErrorMessage(result, t("allFailed")),
        });
        return;
      }
      setState({ phase: "done", results: result.data.results });
      onDone();
    } catch (e) {
      console.error("Failed to update skills", e);
      setState({ phase: "failed", message: t("allFailed") });
    }
  };

  return { state, run, dismiss: () => setState({ phase: "idle" }) };
}

export function UpdateAllSkillsButton({
  state,
  onRun,
}: {
  state: UpdateAll;
  onRun: () => void;
}) {
  const t = useTranslations("SkillsPage.update");
  const running = state.phase === "running";
  return (
    <Button
      className="shrink-0"
      size="xs"
      variant="outline"
      onClick={onRun}
      isLoading={running}
    >
      {!running && <RefreshCw />}
      {t("updateAll")}
    </Button>
  );
}

/** What the last "Update all" did, one row per skill, until dismissed. */
export function UpdateAllSkillsResults({
  state,
  onDismiss,
}: {
  state: UpdateAll;
  onDismiss: () => void;
}) {
  const t = useTranslations("SkillsPage.update");
  if (state.phase === "failed") {
    return <FormError>{state.message}</FormError>;
  }
  if (state.phase !== "done") return null;

  return (
    <section className="rounded-md border border-zinc-200 bg-white card-shadow dark:border-zinc-700 dark:bg-zinc-800">
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700">
        <h2 className="text-sm font-semibold">{t("resultsTitle")}</h2>
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          onClick={onDismiss}
          aria-label={t("dismiss")}
        >
          <X />
        </Button>
      </header>
      {state.results.length === 0 ? (
        <div className="py-4 text-center text-sm text-muted-foreground">
          {t("nothingToUpdate")}
        </div>
      ) : (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-700">
          {state.results.map((result) => {
            const presentation = getSkillUpdateResultPresentation(
              result.status
            );
            return (
              <li
                key={result.skill_id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm"
              >
                <StatusIndicator
                  kind={presentation.kind}
                  size="sm"
                  className="w-28 shrink-0"
                >
                  {t(`results.${result.status}`)}
                </StatusIndicator>
                <Link
                  href={`/skills/${result.skill_id}`}
                  className="min-w-0 truncate font-medium hover:underline"
                >
                  {result.name}
                </Link>
                {result.status === "customized" && (
                  <span className="text-xs text-muted-foreground">
                    {t("customizedSkipped")}
                  </span>
                )}
                {result.error && (
                  <span className="basis-full text-xs text-red-600 dark:text-red-400 sm:basis-auto">
                    {result.error}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
