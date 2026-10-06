"use client";

import { useTranslations } from "next-intl";
import Image from "next/image";
import type {
  AgentResponse,
  ProjectFileInfo,
  ProjectResponse,
} from "@/api/client";
import { AgentAvatar } from "@/components/AgentAvatar";
import {
  AttachmentCard,
  hydrateAttachments,
  type AttachmentItem,
} from "@/components/AttachmentSection";
import FormError from "@/components/FormError";
import { OverviewHero } from "@/components/Overview/OverviewHero";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  addAgentToProjectAction,
  addMcpInstanceToProjectAction,
  addSkillToProjectAction,
  removeAgentFromProjectAction,
  removeMcpInstanceFromProjectAction,
  removeSkillFromProjectAction,
} from "@/lib/server-actions";
import ProjectFilesCard from "./ProjectFilesCard";
import ProjectInstructionsCard from "./ProjectInstructionsCard";

const AgentIcon = ENTITY_ICONS.agent;
const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;
const ProjectIcon = ENTITY_ICONS.project;

/** Row tile size in the section cards — the same as `AgentAvatar` "sm". */
const TILE = 24;

/**
 * A project's overview, drawn from data the page has loaded: the hero, then
 * instructions + agents on the left, skills, connections and files on the
 * right. Every list card adds and removes through the project's own endpoints.
 */
export default function ProjectOverviewView({
  project,
  allAgents,
  allSkills,
  allMcpInstances,
  resourcesLoading,
  instanceIconSrc,
  agentsError,
  files,
  filesError,
  onRetry,
  onChanged,
}: {
  project: ProjectResponse;
  allAgents: AgentResponse[];
  allSkills: AttachmentItem[];
  allMcpInstances: AttachmentItem[];
  resourcesLoading: boolean;
  instanceIconSrc: (instance: AttachmentItem) => string | undefined;
  agentsError: string | null;
  files: ProjectFileInfo[];
  filesError: string | null;
  onRetry: () => void;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("ProjectOverviewPage");
  const tCommon = useTranslations("Common");
  const projectId = project.id;

  return (
    // The hero stays put; only the body below it scrolls, as on the agent page.
    <div className="font-inter md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden">
      <OverviewHero
        mark={
          <EntityAvatar
            size={34}
            rounded={9}
            hue={deterministicHue(project.id)}
            icon={<ProjectIcon strokeWidth={1.85} />}
            className="mt-0.5"
            aria-hidden
          />
        }
        title={project.name}
        status={
          project.parent_project_id ? (
            <Badge
              size="sm"
              variant="outline"
              className="h-5 border-transparent bg-secondary/50 px-1.5 font-normal text-muted-foreground"
            >
              {t("subProject")}
            </Badge>
          ) : undefined
        }
        description={project.description}
        showMoreLabel={t("showMore")}
        showLessLabel={t("showLess")}
      />

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        {agentsError && (
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start">
            <FormError className="flex-1">{agentsError}</FormError>
            <Button
              size="xs"
              variant="outline"
              className="self-start"
              onClick={onRetry}
            >
              {tCommon("retry")}
            </Button>
          </div>
        )}

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          {/* left: how the project works, and who works in it */}
          <div className="flex min-w-0 flex-col gap-4">
            <ProjectInstructionsCard
              projectId={project.id}
              instructions={project.instructions}
            />

            <AttachmentCard
              id="project-agents"
              title={t("agents")}
              icon={AgentIcon}
              addLabel={t("add")}
              sheetTitle={t("agents")}
              sheetDescription={t("agentsSheetDescription")}
              availableTitle={t("availableAgents")}
              attached={hydrateAttachments(project.agents, allAgents)}
              available={allAgents}
              emptyLabel={t("noAgents")}
              emptyAvailable={<p>{t("noAvailableAgents")}</p>}
              onAdd={(item) => addAgentToProjectAction(projectId, item.id)}
              onRemove={(item) =>
                removeAgentFromProjectAction(projectId, item.id)
              }
              onChanged={onChanged}
              renderTile={(agent) => (
                <AgentAvatar
                  agent={{ id: agent.id, name: agent.name }}
                  size="sm"
                />
              )}
              itemHref={(agent) => `/agents/${agent.id}`}
            />
          </div>

          {/* right rail: what the agents may use, and the shared files */}
          <div className="flex min-w-0 flex-col gap-4">
            <AttachmentCard
              id="project-skills"
              title={t("skills")}
              icon={SkillIcon}
              addLabel={t("add")}
              sheetTitle={t("skills")}
              sheetDescription={t("skillsSheetDescription")}
              availableTitle={t("availableSkills")}
              attached={hydrateAttachments(project.skills, allSkills)}
              available={allSkills}
              loading={resourcesLoading}
              emptyLabel={t("noSkills")}
              emptyAvailable={<p>{t("noAvailableSkills")}</p>}
              onAdd={(item) => addSkillToProjectAction(projectId, item.id)}
              onRemove={(item) =>
                removeSkillFromProjectAction(projectId, item.id)
              }
              onChanged={onChanged}
              renderTile={(skill) => (
                <EntityAvatar
                  size={TILE}
                  rounded={7}
                  hue={deterministicHue(skill.id)}
                  icon={<SkillIcon strokeWidth={1.85} />}
                  aria-hidden
                />
              )}
              itemHref={(skill) => `/skills/${skill.id}`}
            />

            <AttachmentCard
              id="project-mcp"
              title={t("connections")}
              icon={McpIcon}
              addLabel={t("add")}
              sheetTitle={t("connections")}
              sheetDescription={t("connectionsSheetDescription")}
              availableTitle={t("availableConnections")}
              attached={hydrateAttachments(
                project.mcp_instances,
                allMcpInstances
              )}
              available={allMcpInstances}
              loading={resourcesLoading}
              emptyLabel={t("noConnections")}
              emptyAvailable={<p>{t("noAvailableConnections")}</p>}
              onAdd={(item) =>
                addMcpInstanceToProjectAction(projectId, item.id)
              }
              onRemove={(item) =>
                removeMcpInstanceFromProjectAction(projectId, item.id)
              }
              onChanged={onChanged}
              getIconSrc={instanceIconSrc}
              renderTile={(instance) => {
                const src = instanceIconSrc(instance);
                return (
                  <EntityAvatar
                    size={TILE}
                    rounded={7}
                    hue={deterministicHue(instance.id)}
                    iconScale={src ? 0.68 : 0.5}
                    icon={
                      src ? (
                        <Image
                          src={src}
                          alt=""
                          aria-hidden="true"
                          width={16}
                          height={16}
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <McpIcon strokeWidth={1.85} />
                      )
                    }
                    aria-hidden
                  />
                );
              }}
              itemHref={(instance) => `/connections/${instance.id}`}
            />

            <ProjectFilesCard
              projectId={project.id}
              files={files}
              error={filesError}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
