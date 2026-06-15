import { createElement } from "react";
import { Boxes, Plug, Sparkles } from "lucide-react";
import {
  agentColorVar,
  getAgentIconComponent,
  resolveAgentIdentity,
} from "@/lib/agent-identity";
import type { Agent } from "@/types/agent";
import { InstallAgentButton } from "./InstallAgentButton";

/**
 * Read-only preview for a built-in catalog agent that has not been forked into
 * the workspace. Catalog agents have no tasks, spend, or guardrails, so we show
 * what the template contains plus an "Add to workspace" CTA instead of the
 * operational dashboard.
 */
export function CatalogAgentPreview({
  agent,
  agentRef,
}: {
  agent: Agent;
  agentRef: string;
}) {
  const { colorToken, iconKey } = resolveAgentIdentity(agent);
  const HeroIcon = getAgentIconComponent(iconKey);

  const modelLabel =
    agent.model_info?.config_name ||
    agent.model_info?.model_display_name ||
    agent.model_id ||
    null;

  const skills = agent.skills ?? [];
  const mcpConfigs = agent.tools_config?.mcp_server_configs ?? [];
  const openapiConfigs = agent.tools_config?.openapi_configs ?? [];
  const connectionsCount = mcpConfigs.length + openapiConfigs.length;

  return (
    <div className="mx-auto w-full max-w-[1180px]">
      {/* ===== hero ===== */}
      <header className="flex items-start gap-4 pb-5">
        <span
          className="relative flex h-[50px] w-[50px] shrink-0 items-center justify-center overflow-hidden rounded-[13px] text-white [&>svg]:relative [&>svg]:z-10 [&>svg]:h-6 [&>svg]:w-6"
          style={{ background: agentColorVar(colorToken) }}
        >
          {createElement(HeroIcon, { strokeWidth: 1.9 })}
          <span className="bg-hatch-on-color pointer-events-none absolute inset-0" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight">
              {agent.name}
            </h1>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-50 px-2.5 py-0.5 text-[11.5px] font-semibold text-violet-700 dark:bg-violet-950/40 dark:text-violet-300">
              <Sparkles className="h-3 w-3" />
              Catalog template
            </span>
          </div>

          {agent.description && (
            <p className="mt-1 max-w-[640px] text-[13px] text-muted-foreground">
              {agent.description}
            </p>
          )}

          {modelLabel && (
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-muted-foreground">
              <span className="inline-flex items-center gap-1.5 [&>svg]:text-muted-foreground/70">
                <Boxes className="h-3.5 w-3.5" />
                <span className="font-medium text-foreground/80">
                  {modelLabel}
                </span>
              </span>
            </div>
          )}

          <div className="mt-4">
            <InstallAgentButton agentRef={agentRef} />
          </div>
        </div>
      </header>

      {/* ===== what's included ===== */}
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
        <Card>
          <CardHead icon={<Sparkles className="h-3.5 w-3.5" />} title="Skills" />
          {skills.length === 0 ? (
            <EmptyRow text="No skills bundled." />
          ) : (
            skills.map((s) => (
              <div
                key={s.id}
                className="border-b border-border/60 px-[15px] py-3 last:border-b-0"
              >
                <div className="text-[12.5px] font-medium">{s.name}</div>
                {s.description && (
                  <div className="truncate text-[11px] text-muted-foreground">
                    {s.description}
                  </div>
                )}
              </div>
            ))
          )}
        </Card>

        <Card>
          <CardHead icon={<Plug className="h-3.5 w-3.5" />} title="Connections" />
          {connectionsCount === 0 ? (
            <EmptyRow text="No connections required." />
          ) : (
            <div className="px-[15px] py-3 text-[12.5px] text-foreground/80">
              {mcpConfigs.length} MCP · {openapiConfigs.length} API
            </div>
          )}
        </Card>
      </div>

      <p className="mt-4 px-1 text-[11px] leading-relaxed text-muted-foreground">
        This is a read-only built-in template. Adding it to your workspace
        creates an editable copy you own — its tasks, budgets and approvals are
        then governed like any other agent.
      </p>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      {children}
    </div>
  );
}

function CardHead({
  icon,
  title,
}: {
  icon: React.ReactNode;
  title: string;
}) {
  return (
    <div className="flex items-center gap-2.5 border-b border-border/60 px-[15px] py-2.5">
      <span className="grid h-[23px] w-[23px] place-items-center rounded-md bg-muted text-foreground/70">
        {icon}
      </span>
      <span className="flex-1 text-[13px] font-semibold">{title}</span>
    </div>
  );
}

function EmptyRow({ text }: { text: string }) {
  return (
    <div className="px-[15px] py-7 text-center text-[12px] text-muted-foreground">
      {text}
    </div>
  );
}
