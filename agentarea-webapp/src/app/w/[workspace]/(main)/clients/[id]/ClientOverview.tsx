"use client";

import { useTranslations } from "next-intl";
import {
  Cpu,
  KeyRound,
  Link2,
  SquareTerminal,
  Users,
  Wrench,
} from "lucide-react";
import type { AgentResponse, ClientResponse } from "@/api/client";
import { AgentAvatar } from "@/components/AgentAvatar";
import { harnessOf } from "@/components/harnesses";
import { DetailsCard } from "@/components/Overview/DetailsCard";
import {
  CardField,
  EmptyRow,
  FactRow,
  GlanceRow,
  HeroMeta,
  SectionCard,
  SectionCardHead,
  SoftTile,
  Stat,
  StatStrip,
} from "@/components/Overview/OverviewCard";
import { OverviewHero } from "@/components/Overview/OverviewHero";
import { CopyableText } from "@/components/ui/copyable-text";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { getRunnerStatusPresentation } from "@/lib/status";
import { agentPath } from "@/types";

/**
 * A harness's overview: the hero, what it serves, how a harness connects, and
 * for a Codex or Claude Code harness its runner and the agents that run on it.
 * `runner` is null for a harness without one; `keyCount` is null for someone
 * who may not edit the harness.
 */
export default function ClientOverview({
  client,
  runner,
}: {
  client: ClientResponse;
  runner: { keyCount: number | null; agents: AgentResponse[] } | null;
}) {
  const t = useTranslations("ClientsPage.overview");
  const tClients = useTranslations("ClientsPage");
  const tRunner = useTranslations("ClientsPage.runner");
  const harness = harnessOf(client.kind);
  const HarnessGlyph = harness.icon;
  const status = getRunnerStatusPresentation(client.online ?? false);
  const statusLabel = tRunner(status.labelKey as "online" | "offline");

  const mcpInstances = client.mcp_instances ?? [];
  const toolsets = client.platform_toolsets ?? [];
  const skills = client.skills ?? [];
  const narrowedMcp = mcpInstances.filter(
    (instance) => instance.allowed_tools != null
  ).length;
  const narrowedToolsets = toolsets.filter(
    (toolset) => (toolset.disabled_methods ?? []).length > 0
  ).length;
  const syncCommand = `agentarea mcp sync --client=${client.id} --target=${
    client.kind === "harness" ? "codex" : client.kind
  }`;

  return (
    <div className="font-inter md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden">
      <OverviewHero
        mark={
          <EntityAvatar
            size={34}
            rounded={9}
            hue={deterministicHue(client.id)}
            icon={<HarnessGlyph />}
            className="mt-0.5"
            aria-hidden
          />
        }
        title={client.name}
        status={
          runner && (
            <StatusIndicator
              kind={status.kind}
              className="whitespace-nowrap text-[13px] font-medium"
            >
              {statusLabel}
            </StatusIndicator>
          )
        }
        description={client.description || t("defaultDescription")}
        showMoreLabel={t("showMore")}
        showLessLabel={t("showLess")}
        meta={
          <>
            <HeroMeta icon={<ENTITY_ICONS.client />}>{harness.label}</HeroMeta>
            {runner && client.default_model && (
              <HeroMeta icon={<Cpu />}>{client.default_model}</HeroMeta>
            )}
          </>
        }
      />

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <StatStrip columns={runner ? 4 : 3}>
          <Stat
            icon={<ENTITY_ICONS.mcp />}
            label={t("stats.mcp")}
            value={mcpInstances.length}
            bar={null}
            sub={
              mcpInstances.length === 0
                ? t("stats.none")
                : narrowedMcp > 0
                  ? t("stats.narrowed", { count: narrowedMcp })
                  : t("stats.allTools")
            }
          />
          <Stat
            icon={<Wrench />}
            label={t("stats.toolsets")}
            value={toolsets.length}
            bar={null}
            sub={
              toolsets.length === 0
                ? t("stats.none")
                : narrowedToolsets > 0
                  ? t("stats.narrowed", { count: narrowedToolsets })
                  : t("stats.allTools")
            }
          />
          <Stat
            icon={<ENTITY_ICONS.skill />}
            label={t("stats.skills")}
            value={skills.length}
            bar={null}
            sub={t("stats.skillsSub")}
          />
          {runner && (
            <Stat
              icon={<Users />}
              label={t("stats.agents")}
              value={runner.agents.length}
              bar={null}
              sub={
                runner.agents.length > 0
                  ? t("stats.agentsSub")
                  : t("stats.agentsNone")
              }
            />
          )}
        </StatStrip>

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            <SectionCard>
              <SectionCardHead icon={<Link2 />} title={t("connection.title")} />
              {client.mcp_endpoint_url && (
                <CardField label={t("connection.endpoint")}>
                  <CopyableText text={client.mcp_endpoint_url} />
                  <p className="note">{t("connection.endpointHint")}</p>
                </CardField>
              )}
              <CardField label={t("connection.sync")}>
                <CopyableText text={syncCommand} />
                <p className="note">{t("connection.syncHint")}</p>
              </CardField>
            </SectionCard>

            {runner && (
              <SectionCard>
                <SectionCardHead
                  icon={<SquareTerminal />}
                  title={tRunner("title")}
                  link={{
                    label: t("runner.manage"),
                    href: `/clients/${client.id}/runner`,
                  }}
                />
                <FactRow
                  tile={<SoftTile icon={<SquareTerminal />} />}
                  title={
                    <StatusIndicator kind={status.kind} size="sm">
                      {statusLabel}
                    </StatusIndicator>
                  }
                  sub={t("runner.status")}
                />
                <FactRow
                  tile={<SoftTile icon={<Cpu />} />}
                  title={client.default_model || t("runner.noModel")}
                  sub={tRunner("model")}
                />
                {runner.keyCount !== null && (
                  <FactRow
                    tile={<SoftTile icon={<KeyRound />} />}
                    title={t("runner.keyCount", { count: runner.keyCount })}
                    sub={tRunner("keys.title")}
                  />
                )}
              </SectionCard>
            )}
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            {runner && (
              <SectionCard className="[&>a:last-child>div]:border-b-0">
                <SectionCardHead
                  icon={<ENTITY_ICONS.agent />}
                  title={tClients("agents.title")}
                  count={runner.agents.length}
                />
                {runner.agents.length === 0 ? (
                  <EmptyRow text={tClients("agents.empty")} />
                ) : (
                  runner.agents.map((agent) => (
                    <GlanceRow
                      key={agent.id}
                      href={agentPath(agent)}
                      tile={<AgentAvatar agent={agent} size="sm" />}
                      title={agent.name}
                      sub={agent.description || t("agentSub")}
                    />
                  ))
                )}
              </SectionCard>
            )}

            <DetailsCard id={client.id} idLabel={t("details.id")} />
          </div>
        </div>
      </div>
    </div>
  );
}
