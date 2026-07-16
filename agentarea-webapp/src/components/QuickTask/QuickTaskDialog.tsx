"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { AgentResponse, ProjectResponse } from "@/api/client/types.gen";
import FullChat, {
  type Agent,
  type ProjectOption,
  type TaskPolicyOption,
} from "@/components/Chat/FullChat";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { Skeleton } from "@/components/ui/skeleton";
import { getAgents } from "@/components/actions";
import { listPoliciesAction, listProjectsAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";

export const QUICK_TASK_OPEN_EVENT = "workplace:quick-task-open";

/** Agents carry a couple of presentational fields not in the generated schema. */
type ApiAgent = AgentResponse & {
  icon?: string | null;
  color_token?: string | null;
};

type ApiProject = ProjectResponse;

/** The /v1/policies endpoint is untyped in the client; describe what we read. */
type ApiPolicy = {
  id: string;
  target?: string | null;
  effect?: string | null;
  params?: Record<string, unknown> | null;
  subject_type?: string | null;
  priority?: number | null;
};

function formatPolicyName(policy: ApiPolicy) {
  const effect = String(policy.effect ?? "policy");
  const target = String(policy.target ?? "*");
  return `${effect} ${target}`;
}

function formatPolicyDescription(policy: ApiPolicy) {
  const subjectType = String(policy.subject_type ?? "workspace");
  const priority = Number.isFinite(policy.priority) ? policy.priority : 0;
  return `${subjectType} - priority ${priority}`;
}

/** Composer-shaped skeleton shown while agents/projects/policies load. */
function QuickTaskComposerSkeleton() {
  return (
    <div className="rounded-2xl border p-3" aria-hidden="true">
      <Skeleton className="h-16 w-full rounded-lg" />
      <div className="mt-3 flex items-center gap-2">
        <Skeleton className="h-7 w-28 rounded-md" />
        <Skeleton className="h-7 w-24 rounded-md" />
        <Skeleton className="h-7 w-32 rounded-md" />
        <div className="ml-auto flex gap-2">
          <Skeleton className="h-8 w-8 rounded-full" />
          <Skeleton className="h-8 w-8 rounded-full" />
        </div>
      </div>
    </div>
  );
}

export default function QuickTaskDialog() {
  const router = useRouter();
  const t = useTranslations("QuickTask");

  const [open, setOpen] = React.useState(false);
  const [dataLoaded, setDataLoaded] = React.useState(false);
  const [agents, setAgents] = React.useState<Agent[]>([]);
  const [projects, setProjects] = React.useState<ProjectOption[]>([]);
  const [policies, setPolicies] = React.useState<TaskPolicyOption[]>([]);
  const [selectedAgent, setSelectedAgent] = React.useState<Agent | null>(null);

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

  // Lazy-load agents + projects + policies on FIRST open only (cached after).
  // Nothing is fetched at app startup — the effect bails out while closed.
  React.useEffect(() => {
    if (!open || dataLoaded) return;
    let cancelled = false;
    Promise.all([getAgents(), listProjectsAction(), listPoliciesAction()])
      .then(([agentsRes, projectsRes, policiesRes]) => {
        if (cancelled) return;
        const agentList: Agent[] = ((agentsRes.data ?? []) as ApiAgent[]).map(
          (a) => ({
            id: String(a.id),
            name: a.name,
            description: a.description ?? null,
            icon: a.icon ?? null,
            color_token: a.color_token ?? null,
          })
        );
        const projectList: ProjectOption[] = (
          (projectsRes.data ?? []) as ApiProject[]
        ).map((p) => ({
          id: String(p.id),
          name: p.name,
          description: p.description ?? null,
        }));
        const policyList: TaskPolicyOption[] = (
          (policiesRes.data ?? []) as ApiPolicy[]
        ).map((p) => ({
          id: String(p.id),
          name: formatPolicyName(p),
          description: formatPolicyDescription(p),
          policy: {
            id: String(p.id),
            target: p.target ?? "",
            effect: p.effect ?? "",
            params: p.params ?? {},
          },
        }));
        setAgents(agentList);
        setProjects(projectList);
        setPolicies(policyList);
        setSelectedAgent((prev) => prev || agentList[0] || null);
        setDataLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setDataLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, dataLoaded]);

  const handleTaskCreated = React.useCallback(
    (taskId: string) => {
      setOpen(false);
      router.push(`/tasks/${taskId}`);
    },
    [router]
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        data-quick-task-dialog
        closeClassName="right-2 top-2"
        className={cn(
          // extra top padding gives the close button its own strip above the composer
          "top-[24%] max-w-2xl translate-y-0 gap-0 overflow-hidden rounded-2xl border bg-background px-3 pb-3 pt-7 shadow-2xl",
          "data-[state=closed]:slide-out-to-top-[20%] data-[state=open]:slide-in-from-top-[20%]"
        )}
      >
        <DialogTitle className="sr-only">{t("title")}</DialogTitle>

        {selectedAgent ? (
          <>
            <FullChat
              agent={selectedAgent}
              availableAgents={agents}
              onAgentChange={setSelectedAgent}
              availableProjects={projects}
              availableTaskPolicies={policies}
              onTaskCreated={handleTaskCreated}
              startCentered
              className="!h-auto !max-w-none !gap-0 !py-0"
            />
            <div className="mt-2.5 flex items-center justify-end gap-4 text-[11px] text-muted-foreground/70">
              <span className="inline-flex items-center gap-1.5">
                <Kbd keys={["↵"]} />
                {t("toCreate")}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Kbd keys={["Esc"]} />
                {t("toClose")}
              </span>
            </div>
          </>
        ) : (
          <QuickTaskComposerSkeleton />
        )}
      </DialogContent>
    </Dialog>
  );
}
