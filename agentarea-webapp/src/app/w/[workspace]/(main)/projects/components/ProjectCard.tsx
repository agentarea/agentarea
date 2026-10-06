import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { FileText, type LucideIcon } from "lucide-react";
import type { ProjectAgentRef, ProjectResponse } from "@/api/client/types.gen";
import { AgentAvatar } from "@/components/AgentAvatar";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { Badge } from "@/components/ui/badge";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";

const ProjectIcon = ENTITY_ICONS.project;

/** How many agent avatars fit in the footer before the rest become "+N". */
const MAX_AGENTS = 4;

/** How many names a tooltip lists before it says "and N more". */
const MAX_NAMES = 8;

// Our dark tooltip over a footer mark: an optional heading, then the names the
// mark stands for. The trigger is a plain span, so Radix can hang its handlers
// and ref on it.
function NamesTooltip({
  label,
  names = [],
  children,
}: {
  label?: string;
  names?: string[];
  children: ReactNode;
}) {
  const t = useTranslations("ProjectsPage");
  const shown = names.slice(0, MAX_NAMES);
  const rest = names.length - shown.length;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex items-center">{children}</span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-56">
        {label && <div className="font-medium">{label}</div>}
        {shown.length > 0 && (
          <ul
            className={label ? "mt-1 space-y-0.5 text-white/70" : "space-y-0.5"}
          >
            {shown.map((name, index) => (
              <li key={index} className="truncate">
                {name}
              </li>
            ))}
            {rest > 0 && (
              <li className="text-white/50">{t("andMore", { count: rest })}</li>
            )}
          </ul>
        )}
      </TooltipContent>
    </Tooltip>
  );
}

// What the project holds, as icon + number; the tooltip spells it out and lists
// the names.
function CountItem({
  icon: Icon,
  count,
  label,
  names,
}: {
  icon: LucideIcon;
  count: number;
  label: string;
  names?: string[];
}) {
  return (
    <NamesTooltip label={label} names={names}>
      <span className="flex items-center gap-1">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        <span className="tabular-nums" aria-hidden>
          {count}
        </span>
        <span className="sr-only">{label}</span>
      </span>
    </NamesTooltip>
  );
}

// The agents themselves, not just their number: the face of who works here.
function AgentStack({
  agents,
  label,
}: {
  agents: ProjectAgentRef[];
  label: string;
}) {
  const shown = agents.slice(0, MAX_AGENTS);
  const hidden = agents.slice(MAX_AGENTS);

  return (
    <span className="flex items-center">
      <span className="flex -space-x-1.5" aria-hidden>
        {shown.map((agent) => (
          <NamesTooltip key={agent.id} label={agent.name}>
            <span className="inline-flex rounded-[6px] ring-2 ring-white dark:ring-zinc-900">
              <AgentAvatar
                agent={{ id: agent.id, name: agent.name }}
                size="xs"
              />
            </span>
          </NamesTooltip>
        ))}
      </span>
      {hidden.length > 0 && (
        <NamesTooltip names={hidden.map((agent) => agent.name)}>
          <span className="ml-1.5 tabular-nums" aria-hidden>
            +{hidden.length}
          </span>
        </NamesTooltip>
      )}
      <span className="sr-only">{label}</span>
    </span>
  );
}

export default function ProjectCard({ project }: { project: ProjectResponse }) {
  const t = useTranslations("ProjectsPage");
  const agents = project.agents ?? [];
  const skills = project.skills ?? [];
  const mcp = project.mcp_instances ?? [];
  const agentsLabel = t("agentsCount", { count: agents.length });

  return (
    <LinkedCard
      href={`/projects/${project.id}`}
      title={project.name}
      bareIcon
      icon={
        <EntityAvatar
          size={40}
          hue={deterministicHue(project.id)}
          icon={<ProjectIcon strokeWidth={1.85} />}
          aria-hidden
        />
      }
      subtitle={
        project.parent_project_id || project.description ? (
          <>
            {project.parent_project_id && (
              <Badge
                size="sm"
                variant="outline"
                className="h-5 border-transparent bg-secondary/50 px-1.5 font-normal text-muted-foreground"
              >
                {t("subProject")}
              </Badge>
            )}
            {project.description && (
              <span className="line-clamp-2 basis-full">
                {project.description}
              </span>
            )}
          </>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-3">
        {project.instructions && (
          <div className="flex items-start gap-1.5 rounded-md bg-muted/50 px-2 py-1.5 text-xs text-muted-foreground">
            <FileText className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
            <span className="line-clamp-2">{project.instructions}</span>
          </div>
        )}

        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {agents.length > 0 ? (
            <AgentStack agents={agents} label={agentsLabel} />
          ) : (
            <CountItem
              icon={ENTITY_ICONS.agent}
              count={0}
              label={agentsLabel}
            />
          )}
          <CountItem
            icon={ENTITY_ICONS.skill}
            count={skills.length}
            label={t("skillsCount", { count: skills.length })}
            names={skills.map((skill) => skill.name)}
          />
          <CountItem
            icon={ENTITY_ICONS.mcp}
            count={mcp.length}
            label={t("mcpCount", { count: mcp.length })}
            names={mcp.map((instance) => instance.name)}
          />
        </div>
      </div>
    </LinkedCard>
  );
}
