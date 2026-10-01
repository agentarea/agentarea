"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { skillDisplay } from "@/lib/skill-display";
import { TaskResourcePanel } from "./TaskResourcePanel";

const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;

export type TaskResourceRef = {
  id: string;
  name?: string | null;
  /**
   * Display-only, resolved the same way the connections list resolves it.
   * Stripped before the task is submitted — the runtime looks a resource up by
   * id, and a logo URL has no business in the run's parameters.
   */
  iconUrl?: string | null;
};

type TaskResourceAttachProps = {
  mcps: TaskResourceRef[];
  skills: TaskResourceRef[];
  onMcpsChange: (next: TaskResourceRef[]) => void;
  onSkillsChange: (next: TaskResourceRef[]) => void;
  disabled?: boolean;
};

/**
 * Attach MCP servers and skills to a single run, on top of whatever the agent
 * already carries.
 *
 * The agent owns its capabilities; this is the one-off addition for a task
 * being written right now, which is why it is additive and unconfigurable —
 * restricting an MCP's tools is a property of the agent, not of one run.
 */
export function TaskResourceAttach({
  mcps,
  skills,
  onMcpsChange,
  onSkillsChange,
  disabled,
}: TaskResourceAttachProps) {
  const t = useTranslations("Pickers");
  const [open, setOpen] = useState(false);
  const names = [
    ...mcps.map((ref) => ref.name ?? ref.id),
    // Read the way the panel lists them, not as the raw imported slug.
    ...skills.map((ref) => skillDisplay({ name: ref.name ?? ref.id }).title),
  ];

  // A count per kind rather than a chip per resource: the chips wrapped the
  // composer's bottom row and crushed the agent and policy pickers beside them.
  // Which ones are attached is a hover away, and the sheet is where they change.
  const counts = [
    { kind: "mcp", Icon: McpIcon, count: mcps.length },
    { kind: "skill", Icon: SkillIcon, count: skills.length },
  ].filter((entry) => entry.count > 0);

  return (
    <TooltipProvider delayDuration={300}>
      <Sheet modal={false} open={open} onOpenChange={setOpen}>
        <Tooltip>
          <SheetTrigger asChild>
            <TooltipTrigger asChild>
              {/* Sized and coloured like the agent/policy pickers beside it,
                  with the attach button's grey hover. */}
              <Button
                type="button"
                variant="ghost"
                size="xs"
                disabled={disabled}
                aria-label={
                  names.length
                    ? `${t("attachTitle")}: ${names.join(", ")}`
                    : t("attachTitle")
                }
                className="h-7 min-w-7 shrink-0 gap-2 rounded-md px-1.5 text-[13px] text-zinc-400 hover:bg-muted hover:text-zinc-500 data-[state=open]:bg-muted data-[state=open]:text-zinc-500 dark:text-zinc-500 dark:hover:bg-muted dark:hover:text-zinc-300 dark:data-[state=open]:text-zinc-300"
              >
                {counts.length ? (
                  counts.map(({ kind, Icon, count }) => (
                    <span key={kind} className="flex items-center gap-1">
                      <Icon />
                      {/* Icon and number take the pickers' two greys. */}
                      <span className="tabular-nums dark:text-zinc-300">
                        {count}
                      </span>
                    </span>
                  ))
                ) : (
                  <Plus />
                )}
              </Button>
            </TooltipTrigger>
          </SheetTrigger>
          <TooltipContent side="top" className="max-w-64">
            {names.length ? (
              <ul className="space-y-0.5">
                {names.map((name, index) => (
                  <li key={index} className="truncate">
                    {name}
                  </li>
                ))}
              </ul>
            ) : (
              t("attachTitle")
            )}
          </TooltipContent>
        </Tooltip>

        <SheetContent
          side="right"
          hideOverlay
          className="flex flex-col gap-0 overflow-hidden p-0 sm:w-[420px] sm:max-w-[420px]"
        >
          <TaskResourcePanel
            mcps={mcps}
            skills={skills}
            onMcpsChange={onMcpsChange}
            onSkillsChange={onSkillsChange}
          />
        </SheetContent>
      </Sheet>
    </TooltipProvider>
  );
}
