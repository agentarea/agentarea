"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface TaskCreatorProps {
  /** tasks.created_by — the principal that started the task. */
  userId?: string | null;
  /** Resolved display name, or null when the identity directory does not know the id. */
  name?: string | null;
}

/**
 * The person a task belongs to, rendered as avatar + name.
 *
 * Shown by `TaskSourceBadge` in place of a "Manual" chip: a task nobody
 * automated came from a person, and naming them says strictly more than the
 * word "Manual" ever did.
 *
 * Clicking filters the list down to that person's tasks — the only navigation
 * a task list can offer that is actually about them; there is no per-user page.
 *
 * An id the directory could not resolve is labelled as unknown and keeps the id
 * in a tooltip. It is deliberately not a link and never renders the raw id as
 * if it were a name: a uuid here is indistinguishable from a person actually
 * called that, which is the same trap `agent_name` avoids.
 */
export function TaskCreator({ userId, name }: TaskCreatorProps) {
  const t = useTranslations("TasksPage");

  if (!userId) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  if (!name) {
    return (
      <TooltipProvider delayDuration={150}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex min-w-0 items-center gap-2">
              <EntityAvatar size={20} text="?" variant="soft" />
              <span className="truncate text-xs italic text-muted-foreground">
                {t("unknownCreator")}
              </span>
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <span className="font-mono text-xs">{userId}</span>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // Only the local part of an email carries a name — the domain would turn
  // alice@example.com into "AE".
  const initials = nameInitials(
    name.includes("@") ? name.slice(0, name.indexOf("@")) : name
  );

  return (
    <Link
      href={`/tasks?creator=${encodeURIComponent(userId)}`}
      // The row is itself clickable; without this the row's navigation wins.
      onClick={(event) => event.stopPropagation()}
      title={t("showTasksBy", { name })}
      className="group/creator inline-flex min-w-0 items-center gap-2 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <EntityAvatar size={20} text={initials} variant="soft" />
      <span className="truncate text-xs text-muted-foreground transition-colors group-hover/creator:text-primary group-hover/creator:underline group-hover/creator:underline-offset-2">
        {name}
      </span>
    </Link>
  );
}
