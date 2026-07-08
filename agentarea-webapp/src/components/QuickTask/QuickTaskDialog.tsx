"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowUp, Loader2, Paperclip, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createTask, getAgents } from "@/components/actions";
import { cn } from "@/lib/utils";

export const QUICK_TASK_OPEN_EVENT = "workplace:quick-task-open";

interface QuickAgent {
  id: string;
  name: string;
}

export default function QuickTaskDialog() {
  const router = useRouter();
  const t = useTranslations("QuickTask");

  const [open, setOpen] = React.useState(false);
  const [agents, setAgents] = React.useState<QuickAgent[]>([]);
  const [agentsLoaded, setAgentsLoaded] = React.useState(false);
  const [currentAgentId, setCurrentAgentId] = React.useState<string>("");
  const [input, setInput] = React.useState("");
  const [isLoading, setIsLoading] = React.useState(false);

  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  // Cmd+J & event listener
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setOpen(true);
      }
    };
    const evtHandler = () => setOpen(true);
    window.addEventListener("keydown", handler);
    window.addEventListener(QUICK_TASK_OPEN_EVENT, evtHandler);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener(QUICK_TASK_OPEN_EVENT, evtHandler);
    };
  }, []);

  // Lazy-load agents on first open
  React.useEffect(() => {
    if (!open || agentsLoaded) return;
    let cancelled = false;
    getAgents()
      .then(({ data }) => {
        if (cancelled) return;
        const list: QuickAgent[] = (data || []).map((a: unknown) => {
          const item = a as { id?: unknown; name?: unknown };
          return { id: String(item.id ?? ""), name: String(item.name ?? "") };
        });
        setAgents(list);
        setCurrentAgentId((prev) => prev || list[0]?.id || "");
        setAgentsLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setAgents([]);
        setAgentsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, agentsLoaded]);

  // Focus on open / reset on close
  React.useEffect(() => {
    if (open) {
      setTimeout(() => textareaRef.current?.focus(), 80);
    } else {
      setInput("");
    }
  }, [open]);

  const submitTask = async () => {
    const trimmed = input.trim();
    if (!trimmed || !currentAgentId || isLoading) return;

    setIsLoading(true);
    try {
      const { data, error } = await createTask(currentAgentId, {
        description: trimmed,
      });
      const taskId = (data as { id?: string } | null | undefined)?.id;
      if (error || !taskId) {
        setIsLoading(false);
        return;
      }
      setOpen(false);
      setInput("");
      setIsLoading(false);
      router.push(`/tasks/${taskId}`);
    } catch {
      setIsLoading(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void submitTask();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submitTask();
    }
  };

  const canSubmit = input.trim().length > 0 && !!currentAgentId && !isLoading;
  const currentAgent = agents.find((a) => a.id === currentAgentId);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        data-quick-task-dialog
        className={cn(
          "top-[28%] max-w-2xl translate-y-0 gap-0 overflow-hidden rounded-2xl border bg-background/95 p-3 shadow-2xl backdrop-blur-sm",
          "data-[state=closed]:slide-out-to-top-[20%] data-[state=open]:slide-in-from-top-[20%]"
        )}
      >
        <DialogTitle className="sr-only">{t("title")}</DialogTitle>

        <div
          className={cn(
            "rounded-xl border bg-background transition-shadow",
            "focus-within:ring-1 focus-within:ring-ring/30"
          )}
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t("placeholderGeneric")}
            disabled={isLoading}
            rows={3}
            className={cn(
              "w-full resize-none bg-transparent px-3.5 pt-3 pb-1 text-sm",
              "outline-none placeholder:text-muted-foreground/70",
              "disabled:opacity-60"
            )}
          />

          <div className="flex items-center justify-between px-2 pb-2">
            <Select value={currentAgentId} onValueChange={setCurrentAgentId}>
              <SelectTrigger
                className={cn(
                  "h-7 w-auto gap-1.5 border-0 bg-transparent px-2 text-xs font-medium",
                  "hover:bg-muted/60 focus:ring-0 focus:ring-offset-0",
                  "[&>svg:last-child]:h-3 [&>svg:last-child]:w-3 [&>svg:last-child]:opacity-60"
                )}
              >
                <Sparkles
                  className="h-3 w-3 text-orange-400"
                  strokeWidth={2}
                  aria-hidden="true"
                />
                <SelectValue placeholder={t("selectAgent")}>
                  {currentAgent?.name ?? t("selectAgent")}
                </SelectValue>
              </SelectTrigger>
              <SelectContent align="start">
                {agents.length === 0 ? (
                  <div className="px-2 py-1.5 text-xs text-muted-foreground">
                    {agentsLoaded ? t("noAgentsShort") : t("loading")}
                  </div>
                ) : (
                  agents.map((agent) => (
                    <SelectItem
                      key={agent.id}
                      value={agent.id}
                      className="text-xs"
                    >
                      {agent.name}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>

            <div className="flex items-center gap-0.5">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled
                className="h-7 w-7 rounded-full text-muted-foreground/70 hover:text-foreground"
                aria-label={t("attach")}
              >
                <Paperclip className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                size="icon"
                onClick={submitTask}
                disabled={!canSubmit}
                className="h-7 w-7 rounded-full"
                aria-label={t("send")}
              >
                {isLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ArrowUp className="h-3.5 w-3.5" strokeWidth={2.25} />
                )}
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-2 flex items-center justify-end px-1">
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground/80">
            <kbd className="rounded border border-border/60 bg-muted/40 px-1 py-0.5 font-mono text-[10px] leading-none">
              &#8984;&#8629;
            </kbd>
            {t("toCreate")}
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
