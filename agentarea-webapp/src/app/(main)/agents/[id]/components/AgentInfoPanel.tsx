"use client";

import {
  Brain,
  Plug,
  Sparkles,
  Webhook,
  Wrench,
} from "lucide-react";
import {
  InfoPanelBody,
  InfoPanelField,
  InfoPanelSection,
  InfoPanelShell,
} from "@/components/InfoPanel";
import { ProviderIcon } from "@/components/ui/provider-icon";
import type { Agent } from "@/types/agent";

export default function AgentInfoPanel({ agent }: { agent: Agent }) {
  const skills = agent.skills ?? [];
  const builtinTools = agent.tools_config?.builtin_tools ?? [];
  const mcpConfigs = agent.tools_config?.mcp_server_configs ?? [];
  const openapiConfigs = agent.tools_config?.openapi_configs ?? [];

  const modelLabel =
    agent.model_info?.model_display_name ||
    agent.model_info?.config_name ||
    agent.model_id ||
    null;
  const providerLabel = agent.model_info?.provider_name ?? null;
  const providerIconUrl = agent.model_info?.provider_icon_url ?? null;

  const instruction = (agent.instruction ?? "").trim();
  const hasTools =
    builtinTools.length + mcpConfigs.length + openapiConfigs.length > 0;

  return (
    <InfoPanelShell>
      <InfoPanelBody>
        <InfoPanelSection title="Model">
          <InfoPanelField label="Provider" icon={Brain}>
            <div className="flex items-center gap-1.5 text-xs text-foreground">
              {providerLabel && (
                <ProviderIcon
                  iconUrl={providerIconUrl}
                  name={providerLabel}
                  size="sm"
                />
              )}
              {providerLabel || "—"}
            </div>
          </InfoPanelField>
          <InfoPanelField label="Model" className="mt-3">
            <div className="flex items-center gap-1.5 text-xs text-foreground">
              {modelLabel && providerLabel && (
                <ProviderIcon
                  iconUrl={providerIconUrl}
                  name={providerLabel}
                  size="sm"
                />
              )}
              {modelLabel || "—"}
            </div>
          </InfoPanelField>
          {agent.planning && (
            <div className="mt-3 text-[11px] text-muted-foreground">
              Planning enabled
            </div>
          )}
        </InfoPanelSection>

        {instruction && (
          <InfoPanelSection title="Instructions">
            <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
              {instruction.length > 320
                ? `${instruction.slice(0, 320).trim()}…`
                : instruction}
            </p>
          </InfoPanelSection>
        )}

        <InfoPanelSection title={`Skills (${skills.length})`}>
          {skills.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">
              No skills configured.
            </p>
          ) : (
            <ul className="space-y-2">
              {skills.map((s) => (
                <li key={s.id} className="flex items-start gap-2">
                  <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium text-foreground">
                      {s.name}
                    </div>
                    {s.description && (
                      <div className="line-clamp-2 text-[11px] text-muted-foreground">
                        {s.description}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </InfoPanelSection>

        {hasTools && (
          <InfoPanelSection title="Tools">
            <div className="space-y-3">
              {builtinTools.length > 0 && (
                <PanelToolGroup
                  icon={<Wrench className="h-3 w-3 text-muted-foreground" />}
                  label="Built-in"
                  count={builtinTools.length}
                  items={builtinTools.map((t) =>
                    String((t as any).tool_name ?? "tool")
                  )}
                />
              )}
              {mcpConfigs.length > 0 && (
                <PanelToolGroup
                  icon={<Plug className="h-3 w-3 text-muted-foreground" />}
                  label="MCP"
                  count={mcpConfigs.length}
                  items={mcpConfigs.map((c) => {
                    const id = String((c as any).server_id ?? "").slice(0, 8);
                    const tools = (c as any).tools as string[] | undefined;
                    return tools && tools.length > 0
                      ? `${id} · ${tools.length}`
                      : id;
                  })}
                />
              )}
              {openapiConfigs.length > 0 && (
                <PanelToolGroup
                  icon={<Webhook className="h-3 w-3 text-muted-foreground" />}
                  label="OpenAPI"
                  count={openapiConfigs.length}
                  items={openapiConfigs.map((c) => {
                    const id = String(
                      (c as any).openapi_connection_id ?? ""
                    ).slice(0, 8);
                    const allowed = (c as any).allowed_tools as
                      | string[]
                      | undefined;
                    return allowed && allowed.length > 0
                      ? `${id} · ${allowed.length}`
                      : id;
                  })}
                />
              )}
            </div>
          </InfoPanelSection>
        )}
      </InfoPanelBody>
    </InfoPanelShell>
  );
}

function PanelToolGroup({
  icon,
  label,
  count,
  items,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
  items: string[];
}) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {icon}
        <span>{label}</span>
        <span className="ml-auto tabular-nums normal-case tracking-normal text-muted-foreground">
          {count}
        </span>
      </div>
      <div className="flex flex-wrap gap-1">
        {items.map((it, i) => (
          <span
            key={`${it}-${i}`}
            className="inline-flex max-w-full truncate rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-foreground/80"
          >
            {it}
          </span>
        ))}
      </div>
    </div>
  );
}
