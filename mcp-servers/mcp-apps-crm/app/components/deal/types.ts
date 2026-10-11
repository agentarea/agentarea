import type { ActivityType } from "@shared/crm";
import type { ActivityRow } from "@shared/schema";
import type { MoveTarget } from "@/lib/pipeline";

export type NewActivity = { type: ActivityType; subject: string; note: string; dueAt?: string; done: boolean };

/** Which control a change came from, so its progress and errors show next to it. */
export type Where = "stage" | "status" | "title" | "close" | "log" | "refresh" | "link" | (string & {});

export type DealState = { busy: Where | null; issue: { where: Where; text: string } | null };

export type DealActions = {
  onMove: (target: MoveTarget | { reopen: true }, where: "stage" | "status") => void;
  onUpdate: (where: Where, args: Record<string, unknown>) => void;
  onLog: (activity: NewActivity) => Promise<boolean>;
  onToggle: (activity: ActivityRow, done: boolean) => void;
  onOpenPipeline: () => void;
  onRefresh: () => void;
};

export const noteFor = (state: DealState, where: Where) =>
  state.issue?.where === where ? state.issue.text : undefined;
