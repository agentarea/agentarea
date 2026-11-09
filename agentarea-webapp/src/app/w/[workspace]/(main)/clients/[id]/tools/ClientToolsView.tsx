"use client";

import { useTranslations } from "next-intl";
import type { ClientResponse, PlatformToolsetResponse } from "@/api/client";
import {
  AttachmentCard,
  hydrateAttachments,
} from "@/components/AttachmentSection";
import EntityMark from "@/components/EntityMark";
import {
  EmptyRow,
  SectionCard,
  SectionCardHead,
} from "@/components/Overview/OverviewCard";
import { SkillTile } from "@/components/SkillTile";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { mcpRefIdentity } from "@/lib/mcp/resolveMcpRef";
import {
  addMcpInstanceToClientAction,
  addPlatformToolsetToClientAction,
  addSkillToClientAction,
  removeMcpInstanceFromClientAction,
  removePlatformToolsetFromClientAction,
  removeSkillFromClientAction,
} from "@/lib/server-actions";
import {
  McpInstanceTools,
  PlatformToolsetMethods,
  type McpToolsResult,
} from "../ToolSelection";

const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;
const ToolIcon = ENTITY_ICONS.tool;

/**
 * What a harness serves through its endpoint: the attached connections,
 * toolsets and skills in the rail, and on the left the tools of each connection
 * and toolset, where the ones the harness should not see are unchecked.
 */
export default function ClientToolsView({
  client,
  platformCatalog,
  catalogError,
  mcpTools,
}: {
  client: ClientResponse;
  platformCatalog: PlatformToolsetResponse[] | null;
  catalogError: string | null;
  mcpTools: Record<string, McpToolsResult>;
}) {
  const t = useTranslations("ClientsPage.tools");
  const router = useWorkspaceRouter();
  const resources = useAttachableResources();
  const { skills: allSkills, mcpInstances: allMcp, mcpServers } = resources;
  const refresh = () => router.refresh();

  const mcpInstances = client.mcp_instances ?? [];
  const toolsets = client.platform_toolsets ?? [];
  const toolsetItems = (platformCatalog ?? []).map((toolset) => ({
    id: toolset.name,
    name: toolset.display_name,
    description: toolset.description,
  }));
  const mcpMark = (id: string, className: string) => (
    <EntityMark
      identity={mcpRefIdentity(id, allMcp, mcpServers)}
      className={className}
    />
  );
  const servedSub = (narrowed: number | null) =>
    narrowed === null ? t("allServed") : t("someServed", { count: narrowed });

  return (
    <div className="font-inter h-full w-full overflow-y-auto overscroll-contain bg-muted/20 px-4 pb-11 pt-[18px]">
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          {mcpInstances.length === 0 && toolsets.length === 0 && (
            <SectionCard>
              <SectionCardHead icon={<ToolIcon />} title={t("servedTitle")} />
              <EmptyRow text={t("servedEmpty")} />
            </SectionCard>
          )}

          {mcpInstances.map((attachment) => (
            <SectionCard key={attachment.id}>
              <SectionCardHead
                icon={mcpMark(attachment.id, "h-3.5 w-3.5 rounded-sm")}
                title={
                  allMcp.find((instance) => instance.id === attachment.id)
                    ?.name ?? attachment.name
                }
                link={{
                  label: t("openConnection"),
                  href: `/connections/${attachment.id}`,
                }}
              />
              <McpInstanceTools
                clientId={client.id}
                attachment={attachment}
                result={mcpTools[attachment.id]}
                onSaved={refresh}
              />
            </SectionCard>
          ))}

          {toolsets.map((attachment) => {
            const toolset = platformCatalog?.find(
              (entry) => entry.name === attachment.name
            );
            return (
              <SectionCard key={attachment.name}>
                <SectionCardHead
                  icon={<ToolIcon />}
                  title={toolset?.display_name ?? attachment.name}
                />
                <PlatformToolsetMethods
                  clientId={client.id}
                  attachment={attachment}
                  toolset={toolset}
                  onSaved={refresh}
                />
              </SectionCard>
            );
          })}
        </div>

        <div className="order-first flex min-w-0 flex-col gap-4 lg:order-none">
          <AttachmentCard
            id="client-mcp"
            title={t("mcp.title")}
            icon={McpIcon}
            addLabel={t("add")}
            sheetTitle={t("mcp.title")}
            sheetDescription={t("mcp.sheetDescription")}
            availableTitle={t("mcp.available")}
            attached={hydrateAttachments(mcpInstances, allMcp)}
            available={allMcp}
            loading={resources.loading}
            emptyLabel={t("mcp.empty")}
            emptyAvailable={<p>{t("mcp.noneAvailable")}</p>}
            onAdd={(item) => addMcpInstanceToClientAction(client.id, item.id)}
            onRemove={(item) =>
              removeMcpInstanceFromClientAction(client.id, item.id)
            }
            onChanged={refresh}
            renderMark={(item) => mcpMark(item.id, "h-4 w-4 rounded-sm")}
            renderTile={(item) =>
              mcpMark(item.id, "h-6 w-6 shrink-0 rounded-[7px]")
            }
            renderSub={(item) => {
              const allowed = mcpInstances.find(
                (instance) => instance.id === item.id
              )?.allowed_tools;
              return servedSub(allowed == null ? null : allowed.length);
            }}
            itemHref={(item) => `/connections/${item.id}`}
          />

          <AttachmentCard
            id="client-platform"
            title={t("toolsets.title")}
            icon={ToolIcon}
            addLabel={t("add")}
            sheetTitle={t("toolsets.title")}
            sheetDescription={t("toolsets.sheetDescription")}
            availableTitle={t("toolsets.available")}
            attached={hydrateAttachments(
              toolsets.map((toolset) => ({
                id: toolset.name,
                name: toolset.name,
              })),
              toolsetItems
            )}
            available={toolsetItems}
            loading={platformCatalog === null && catalogError === null}
            emptyLabel={t("toolsets.empty")}
            emptyAvailable={
              <p>{catalogError ?? t("toolsets.noneAvailable")}</p>
            }
            onAdd={(item) =>
              addPlatformToolsetToClientAction(client.id, item.id, null)
            }
            onRemove={(item) =>
              removePlatformToolsetFromClientAction(client.id, item.id)
            }
            onChanged={refresh}
            renderTile={(item) => (
              <EntityAvatar
                size={24}
                rounded={7}
                hue={deterministicHue(item.id)}
                icon={<ToolIcon strokeWidth={1.85} />}
                aria-hidden
              />
            )}
            renderSub={(item) => {
              const off = toolsets.find(
                (toolset) => toolset.name === item.id
              )?.disabled_methods;
              return off && off.length > 0
                ? t("someOff", { count: off.length })
                : t("allServed");
            }}
          />

          <AttachmentCard
            id="client-skills"
            title={t("skills.title")}
            icon={SkillIcon}
            addLabel={t("add")}
            sheetTitle={t("skills.title")}
            sheetDescription={t("skills.sheetDescription")}
            availableTitle={t("skills.available")}
            attached={hydrateAttachments(client.skills, allSkills)}
            available={allSkills}
            loading={resources.loading}
            emptyLabel={t("skills.empty")}
            emptyAvailable={<p>{t("skills.noneAvailable")}</p>}
            onAdd={(item) => addSkillToClientAction(client.id, item.id)}
            onRemove={(item) => removeSkillFromClientAction(client.id, item.id)}
            onChanged={refresh}
            renderMark={(item) => <SkillTile skillId={item.id} />}
            renderTile={(skill) => (
              <EntityAvatar
                size={24}
                rounded={7}
                hue={deterministicHue(skill.id)}
                icon={<SkillIcon strokeWidth={1.85} />}
                aria-hidden
              />
            )}
            itemHref={(skill) => `/skills/${skill.id}`}
          />
        </div>
      </div>
    </div>
  );
}
