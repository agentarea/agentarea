"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { ListPlus, Loader2, ThumbsDown, ThumbsUp } from "lucide-react";
import type { FeedbackResponse, SuiteResponse } from "@/api/client/types.gen";
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
import { cn } from "@/lib/utils";
import {
  addCaseFromTaskAction,
  rateRunAction,
} from "../../../shared/evalActions";

/** A person's verdict on this run, and a way to keep the run as a test case. */
export default function RunFeedbackBar({
  taskId,
  mine,
  suites,
}: {
  taskId: string;
  mine: FeedbackResponse | null;
  suites: SuiteResponse[];
}) {
  const t = useTranslations("AgentEvals.feedback");
  const [rating, setRating] = useState<"good" | "bad" | null>(
    mine ? (mine.rating as "good" | "bad") : null
  );
  const [comment, setComment] = useState(mine?.comment ?? "");
  const [suiteId, setSuiteId] = useState(suites[0]?.id ?? "");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const save = (next: "good" | "bad") => {
    setRating(next);
    setError(null);
    startTransition(async () => {
      const result = await rateRunAction(
        taskId,
        next,
        next === "bad" ? comment : ""
      );
      if (!result.ok) setError(result.error);
      else setNotice(t("saved"));
    });
  };

  const addToSuite = () => {
    setError(null);
    startTransition(async () => {
      const result = await addCaseFromTaskAction(suiteId, taskId);
      if (!result.ok) setError(result.error);
      else setNotice(t("added"));
    });
  };

  return (
    <div className="mt-4 space-y-3 border-t pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{t("title")}</span>
        <Button
          size="xs"
          variant="outline"
          className={cn(
            rating === "good" && "border-[color:var(--status-success)]"
          )}
          onClick={() => save("good")}
          disabled={pending}
          aria-pressed={rating === "good"}
        >
          <ThumbsUp />
          {t("good")}
        </Button>
        <Button
          size="xs"
          variant="outline"
          className={cn(
            rating === "bad" && "border-[color:var(--status-danger)]"
          )}
          onClick={() => setRating("bad")}
          disabled={pending}
          aria-pressed={rating === "bad"}
        >
          <ThumbsDown />
          {t("bad")}
        </Button>
        {pending && <Loader2 className="h-4 w-4 animate-spin" />}
        {notice && !pending && (
          <StatusIndicator kind="done" size="sm">
            {notice}
          </StatusIndicator>
        )}
      </div>
      {rating === "bad" && (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            className="max-w-md"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={t("comment")}
          />
          <Button size="xs" onClick={() => save("bad")} disabled={pending}>
            {t("save")}
          </Button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {suites.length === 0 ? (
          <p className="note">{t("noSuites")}</p>
        ) : (
          <>
            <Select value={suiteId} onValueChange={setSuiteId}>
              <SelectTrigger className="w-[220px]">
                <SelectValue placeholder={t("chooseSuite")} />
              </SelectTrigger>
              <SelectContent>
                {suites.map((suite) => (
                  <SelectItem key={suite.id} value={suite.id}>
                    {suite.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="xs"
              variant="outline"
              onClick={addToSuite}
              disabled={pending || !suiteId}
            >
              <ListPlus />
              {t("addToSuite")}
            </Button>
          </>
        )}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
