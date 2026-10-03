"use client";

import { useEffect, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { ListPlus, Loader2, ThumbsDown, ThumbsUp } from "lucide-react";
import type { SuiteResponse } from "@/api/client/types.gen";
import {
  addCaseFromTaskAction,
  loadRunFeedbackAction,
  rateRunAction,
} from "@/app/w/[workspace]/(main)/agents/shared/evalActions";
import { InfoPanelSection } from "@/components/InfoPanel";
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

type Rating = "good" | "bad";

/** A person's verdict on this run, and a way to keep the run as a test case. */
export default function RunFeedback({ taskId }: { taskId: string }) {
  const t = useTranslations("AgentEvals.feedback");
  const [loaded, setLoaded] = useState(false);
  const [rating, setRating] = useState<Rating | null>(null);
  const [comment, setComment] = useState("");
  const [suites, setSuites] = useState<SuiteResponse[]>([]);
  const [suiteId, setSuiteId] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    let current = true;
    loadRunFeedbackAction(taskId).then((result) => {
      if (!current) return;
      if (!result.ok) {
        setError(result.error);
      } else {
        setRating((result.data.mine?.rating as Rating | undefined) ?? null);
        setComment(result.data.mine?.comment ?? "");
        setSuites(result.data.suites);
        setSuiteId(result.data.suites[0]?.id ?? "");
      }
      setLoaded(true);
    });
    return () => {
      current = false;
    };
  }, [taskId]);

  const save = (next: Rating) => {
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

  if (!loaded) return null;

  return (
    <InfoPanelSection title={t("title")} contentClassName="space-y-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2">
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
        <div className="flex items-center gap-2">
          <Input
            className="h-8 text-xs"
            aria-label={t("comment")}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={t("comment")}
          />
          <Button size="xs" onClick={() => save("bad")} disabled={pending}>
            {t("save")}
          </Button>
        </div>
      )}
      {suites.length === 0 ? (
        <p className="text-muted-foreground">{t("noSuites")}</p>
      ) : (
        <div className="flex items-center gap-2">
          <Select value={suiteId} onValueChange={setSuiteId}>
            <SelectTrigger
              className="h-8 min-w-0 flex-1 text-xs"
              aria-label={t("chooseSuite")}
            >
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
        </div>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </InfoPanelSection>
  );
}
