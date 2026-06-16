import { useTranslations } from "next-intl";
import { Clock, Sparkles, SquareTerminal } from "lucide-react";
import { describeToolCall } from "@/components/Chat/utils/describeToolCall";
import { scrollToToolCall } from "@/components/Chat/utils/scrollToToolCall";
import Section from "./Section";

export interface ToolUsage {
  name: string;
  count: number;
  failed: number;
  /** What was called from this tool (commands / queries / paths). */
  uses: string[];
  /** tool_call_ids of every invocation — used to deep-link into the timeline. */
  callIds: string[];
}

export interface ServiceGroup {
  key: string;
  name: string;
  /** Logo URL for an MCP server. */
  icon?: string;
  isMcp: boolean;
  count: number;
  durationSec: number;
  firstCallId?: string;
  tools: ToolUsage[];
}

export interface LearnedSkill {
  name: string;
  callId?: string;
}

export interface TaskActivitySummary {
  events: number;
  llmCalls: number;
  totalTokens: number;
  totalCost: number;
  toolsCalled: number;
  toolsFailed: number;
  uniqueTools: string[];
  services: ServiceGroup[];
  files: string[];
  learnedSkills: LearnedSkill[];
  delegatedAgents: string[];
}

interface ActivitySummaryProps {
  summary?: TaskActivitySummary;
}

function formatDuration(sec: number): string {
  if (sec <= 0) return "";
  if (sec < 60) return `${sec.toFixed(sec < 10 ? 1 : 0)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

function ServiceIcon({ service }: { service: ServiceGroup }) {
  if (service.icon) {
    return (
      <img
        src={service.icon}
        alt=""
        className="h-4 w-4 shrink-0 rounded-sm object-contain"
      />
    );
  }
  if (service.isMcp) {
    return (
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-sm bg-primary/15 text-[9px] font-semibold uppercase text-primary">
        {service.name.charAt(0)}
      </span>
    );
  }
  return <SquareTerminal className="h-4 w-4 shrink-0 text-muted-foreground" />;
}

export default function ActivitySummary({ summary }: ActivitySummaryProps) {
  const t = useTranslations("TaskInfoPanel");

  if (!summary) {
    return null;
  }

  const hasUsage = summary.totalTokens > 0 || summary.totalCost > 0;
  const isEmpty =
    summary.services.length === 0 &&
    summary.learnedSkills.length === 0 &&
    !hasUsage;
  if (isEmpty) {
    return null;
  }

  return (
    <Section title={t("activitySummary")} contentClassName="space-y-3 text-xs">
      {summary.services.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("servicesUsed")}
          </div>
          <div className="space-y-1.5">
            {summary.services.map((service) => (
              <div
                key={service.key}
                className="px-0.5 py-1"
              >
                <button
                  type="button"
                  onClick={() => scrollToToolCall(service.firstCallId)}
                  className="flex w-full items-center gap-1.5 text-left hover:opacity-80"
                  title={t("jumpToUsage")}
                >
                  <ServiceIcon service={service} />
                  <span className="flex-1 truncate font-medium text-foreground">{service.name}</span>
                  {service.isMcp ? (
                    <span className="rounded bg-primary/10 px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide text-primary">
                      MCP
                    </span>
                  ) : (
                    service.durationSec > 0 && (
                      <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                        <Clock className="h-2.5 w-2.5" />
                        {formatDuration(service.durationSec)}
                      </span>
                    )
                  )}
                  <span className="text-[10px] text-muted-foreground">{service.count}</span>
                </button>
                {service.isMcp && (
                  <ul className="mt-1 space-y-1 pl-5">
                    {service.tools.map((tool) => (
                      <li key={tool.name}>
                        <button
                          type="button"
                          onClick={() => scrollToToolCall(tool.callIds[0])}
                          className="flex w-full items-center gap-1.5 text-left hover:text-primary"
                          title={t("jumpToUsage")}
                        >
                          <span className="flex-1 truncate text-[11px] text-foreground/90">
                            {describeToolCall(tool.name).text}
                          </span>
                          {tool.count > 1 && (
                            <span className="text-[10px] text-muted-foreground">×{tool.count}</span>
                          )}
                          {tool.failed > 0 && (
                            <span className="text-[10px] text-destructive">{tool.failed} failed</span>
                          )}
                        </button>
                        {tool.uses.map((u, i) => (
                          <div
                            key={i}
                            className="truncate pl-0 font-mono text-[10px] text-muted-foreground"
                            title={u}
                          >
                            {u}
                          </div>
                        ))}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {summary.learnedSkills.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Sparkles className="h-3 w-3 text-purple-600 dark:text-purple-400" />
            {t("learnedSkills")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {summary.learnedSkills.map((skill) => (
              <button
                key={skill.name}
                type="button"
                onClick={() => scrollToToolCall(skill.callId)}
                title={t("jumpToUsage")}
                className="inline-flex h-auto items-center rounded-md bg-purple-50 px-2 py-0.5 text-[10px] font-normal text-purple-700 transition-colors hover:bg-purple-100 dark:bg-purple-900/30 dark:text-purple-300 dark:hover:bg-purple-900/50"
              >
                {skill.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {hasUsage && (
        <div className="flex items-center justify-between border-t border-border/60 pt-2 text-[11px] text-muted-foreground">
          <span>{t("usage")}</span>
          <span className="tabular-nums">
            {summary.totalTokens.toLocaleString()} {t("tokensShort")} · ${summary.totalCost.toFixed(4)}
          </span>
        </div>
      )}
    </Section>
  );
}
