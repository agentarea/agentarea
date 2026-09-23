"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, X } from "lucide-react";
import ConfigSheet from "@/components/ConfigSheet";
import { Button } from "@/components/ui/button";
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
  const attached = [
    ...mcps.map((ref) => ({ ref, kind: "mcp" as const })),
    ...skills.map((ref) => ({ ref, kind: "skill" as const })),
  ];

  const detach = (kind: "mcp" | "skill", id: string) =>
    kind === "mcp"
      ? onMcpsChange(mcps.filter((item) => item.id !== id))
      : onSkillsChange(skills.filter((item) => item.id !== id));

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1">
      {attached.map(({ ref, kind }) => {
        const Icon = kind === "mcp" ? McpIcon : SkillIcon;
        return (
          <span
            key={`${kind}:${ref.id}`}
            className="flex max-w-[12rem] items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
          >
            {ref.iconUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={ref.iconUrl}
                alt=""
                aria-hidden="true"
                className="h-3.5 w-3.5 shrink-0 rounded-sm object-contain"
              />
            ) : (
              <Icon className="h-3 w-3 shrink-0" />
            )}
            <span className="truncate">{ref.name ?? ref.id}</span>
            <button
              type="button"
              onClick={() => detach(kind, ref.id)}
              disabled={disabled}
              aria-label={t("detach", { name: ref.name ?? ref.id })}
              className="shrink-0 hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        );
      })}

      <ConfigSheet
        title={t("attachTitle")}
        description={t("attachDescription")}
        open={open}
        onOpenChange={setOpen}
        triggerComponent={
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={disabled}
            aria-label={t("attachTitle")}
            className="h-7 w-7 text-muted-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
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
    </div>
  );
}
