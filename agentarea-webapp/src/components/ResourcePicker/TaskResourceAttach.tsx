"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import ConfigSheet from "@/components/ConfigSheet";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { resolveMcpRef } from "@/lib/mcp/resolveMcpRef";
import { McpPicker } from "./McpPicker";
import { SkillPicker } from "./SkillPicker";

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
 * restricting an MCP's tools is a property of the agent, not of one run. The
 * pickers are the same ones the agent's own configuration uses, so a server
 * reads identically in both places.
 */
/**
 * The pickers themselves, split out so the three list requests fire when the
 * sheet is opened rather than on every composer render — this control sits in
 * the chat input, which is mounted on every page.
 */
function AttachPickers({
  mcps,
  skills,
  onMcpsChange,
  onSkillsChange,
}: Omit<TaskResourceAttachProps, "disabled">) {
  const t = useTranslations("Pickers");
  const resources = useAttachableResources();

  // Same resolver the picker and the connections list use, so an attached
  // server carries the logo you picked it by instead of a generic plug.
  const resolveIcon = (instanceId: string) => {
    const resolved = resolveMcpRef(
      instanceId,
      resources.mcpInstances,
      resources.mcpServers
    );
    return resolved.status === "unresolved" ? null : (resolved.iconSrc ?? null);
  };

  return (
    <div className="flex min-h-0 flex-col gap-5 overflow-y-auto pb-6">
      <section className="space-y-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <McpIcon className="h-4 w-4 text-muted-foreground" />
          {t("mcpsHeading")}
        </h3>
        <McpPicker
          resources={resources}
          selectedIds={mcps.map((mcp) => mcp.id)}
          onAdd={(instance) =>
            onMcpsChange(
              mcps.some((item) => item.id === instance.id)
                ? mcps
                : [
                    ...mcps,
                    {
                      id: instance.id,
                      name: instance.name,
                      iconUrl: resolveIcon(instance.id),
                    },
                  ]
            )
          }
          onRemove={(instance) =>
            onMcpsChange(mcps.filter((item) => item.id !== instance.id))
          }
        />
      </section>

      <section className="space-y-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <SkillIcon className="h-4 w-4 text-muted-foreground" />
          {t("skillsHeading")}
        </h3>
        <SkillPicker
          resources={resources}
          selectedIds={skills.map((skill) => skill.id)}
          onAdd={(skill) =>
            onSkillsChange(
              skills.some((item) => item.id === skill.id)
                ? skills
                : [...skills, { id: skill.id, name: skill.name }]
            )
          }
          onRemove={(skill) =>
            onSkillsChange(skills.filter((item) => item.id !== skill.id))
          }
        />
      </section>
    </div>
  );
}

export function TaskResourceAttach({
  mcps,
  skills,
  onMcpsChange,
  onSkillsChange,
  disabled,
}: TaskResourceAttachProps) {
  const t = useTranslations("Pickers");
  const [open, setOpen] = useState(false);
  const names = [...mcps, ...skills].map((ref) => ref.name ?? ref.id);

  // A count per kind rather than a chip per resource: the chips wrapped the
  // composer's bottom row and crushed the agent and policy pickers beside them.
  // Which ones are attached is a hover away, and the sheet is where they change.
  const counts = [
    { kind: "mcp", Icon: McpIcon, count: mcps.length },
    { kind: "skill", Icon: SkillIcon, count: skills.length },
  ].filter((entry) => entry.count > 0);

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <ConfigSheet
          title={t("attachTitle")}
          description={t("attachDescription")}
          open={open}
          onOpenChange={setOpen}
          triggerComponent={
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
          }
        >
          {open && (
            <AttachPickers
              mcps={mcps}
              skills={skills}
              onMcpsChange={onMcpsChange}
              onSkillsChange={onSkillsChange}
            />
          )}
        </ConfigSheet>
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
    </TooltipProvider>
  );
}
