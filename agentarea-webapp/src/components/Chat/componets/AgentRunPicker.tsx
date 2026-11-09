import { useState } from "react";
import { useTranslations } from "next-intl";
import { Check, ChevronDown } from "lucide-react";
import { getHarnessAgentAction } from "@/components/actions";
import { AgentAvatar } from "@/components/AgentAvatar";
import { HarnessIcon, harnessOf } from "@/components/harnesses";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { runsOn, type Runner, type RunOptions } from "@/lib/run-targets";
import { cn } from "@/lib/utils";
import type { Agent } from "../FullChat";

interface AgentRunPickerProps {
  agent: Agent;
  agents?: Agent[];
  onAgentChange?: (agent: Agent) => void;
  runOptions?: RunOptions | null;
  disabled?: boolean;
}

function Row({
  icon,
  name,
  detail,
  selected,
}: {
  icon: React.ReactNode;
  name: string;
  detail?: string | null;
  selected: boolean;
}) {
  return (
    <span className="grid w-full min-w-0 grid-cols-[auto,minmax(0,1fr),auto] items-center gap-x-2">
      {icon}
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="truncate">{name}</span>
        {detail ? (
          <span className="truncate text-[11px] text-zinc-500 dark:text-zinc-400">
            {detail}
          </span>
        ) : null}
      </span>
      <Check
        className={cn(
          "h-3.5 w-3.5 shrink-0",
          selected ? "opacity-100" : "opacity-0"
        )}
      />
    </span>
  );
}

/**
 * Who takes the task: an agent, which runs where it is set up to, or a harness
 * (a Codex or Claude Code CLI) given the task directly with no agent configured.
 */
export function AgentRunPicker({
  agent,
  agents,
  onAgentChange,
  runOptions,
  disabled,
}: AgentRunPickerProps) {
  const t = useTranslations("Chat.inputControls");
  const [error, setError] = useState<string | null>(null);
  const canSwitch = Boolean(onAgentChange);
  const harnesses = canSwitch ? (runOptions?.runners ?? []) : [];

  const runnerDetail = (runner: Runner) =>
    [runner.default_model, runner.online ? null : t("runnerOffline")]
      .filter(Boolean)
      .join(" · ");

  const agentDetail = (candidate: Agent) => {
    if (!runOptions) return null;
    const where = runsOn(
      { modelId: candidate.modelId ?? null, client: candidate.client ?? null },
      runOptions
    );
    if (!where) return null;
    return where.on === "platform"
      ? where.model.name
      : `${harnessOf(where.runner.kind).label} · ${where.runner.name}`;
  };

  const model = (() => {
    if (!runOptions) return null;
    const where = runsOn(
      { modelId: agent.modelId ?? null, client: agent.client ?? null },
      runOptions
    );
    if (!where) return null;
    return where.on === "platform"
      ? where.model.name
      : (where.runner.default_model ?? where.runner.name);
  })();

  const pickHarness = async (runner: Runner) => {
    setError(null);
    const result = await getHarnessAgentAction(runner.id);
    if (result.ok) onAgentChange?.(result.agent);
    else setError(result.error);
  };

  const itemClass =
    "min-h-8 rounded-sm px-2 py-1.5 text-[13px] font-normal text-zinc-800 focus:bg-zinc-100/90 dark:text-zinc-100 dark:focus:bg-zinc-900";
  const labelClass = "px-2 pb-1 pt-1.5 text-[11px] font-medium text-zinc-500";
  const harnessKind = agent.harnessClientId ? agent.client?.kind : null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        disabled={disabled || !canSwitch}
        aria-label={t("agent")}
        title={error ?? undefined}
        className={cn(
          "group flex h-7 w-fit min-w-0 max-w-full items-center gap-1.5 rounded-md border border-transparent bg-transparent pl-1.5 pr-1.5 text-left outline-none",
          "transition-colors duration-150 ease-out hover:bg-zinc-100/70 data-[state=open]:bg-zinc-100/80 disabled:cursor-default disabled:hover:bg-transparent",
          "dark:hover:bg-zinc-800/80 dark:data-[state=open]:bg-zinc-800/80"
        )}
      >
        {harnessKind ? (
          <HarnessIcon kind={harnessKind} className="h-4 w-4 shrink-0" />
        ) : (
          <AgentAvatar agent={agent} size="xs" className="shrink-0" />
        )}
        <span
          className={cn(
            "min-w-0 truncate pb-px text-[13px] leading-[1.2] text-zinc-600 dark:text-zinc-300",
            error && "text-destructive"
          )}
        >
          {agent.name}
        </span>
        {model ? (
          <span className="min-w-0 truncate pb-px text-[13px] leading-[1.2] text-zinc-400 dark:text-zinc-500">
            {model}
          </span>
        ) : null}
        {canSwitch ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400 dark:text-zinc-500" />
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={8}
        className={cn(
          "max-h-[min(28rem,var(--radix-dropdown-menu-content-available-height))] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-md border border-zinc-200/90 bg-white p-1 text-zinc-900",
          "shadow-[0_12px_32px_rgba(15,23,42,0.10),0_2px_6px_rgba(15,23,42,0.04)]",
          "dark:border-zinc-800 dark:bg-zinc-950/95 dark:text-zinc-100"
        )}
      >
        {agents?.length ? (
          <>
            <DropdownMenuLabel className={labelClass}>
              {t("agents")}
            </DropdownMenuLabel>
            {agents.map((candidate) => (
              <DropdownMenuItem
                key={candidate.id}
                className={itemClass}
                onSelect={() => onAgentChange?.(candidate)}
              >
                <Row
                  icon={
                    <AgentAvatar
                      agent={candidate}
                      size="xs"
                      className="shrink-0"
                    />
                  }
                  name={candidate.name}
                  detail={agentDetail(candidate)}
                  selected={candidate.id === agent.id}
                />
              </DropdownMenuItem>
            ))}
          </>
        ) : null}
        {harnesses.length > 0 ? (
          <>
            {agents?.length ? <DropdownMenuSeparator /> : null}
            <DropdownMenuLabel className={labelClass}>
              {t("harnesses")}
            </DropdownMenuLabel>
            {harnesses.map((runner) => (
              <DropdownMenuItem
                key={runner.id}
                className={itemClass}
                onSelect={() => void pickHarness(runner)}
              >
                <Row
                  icon={
                    <HarnessIcon
                      kind={runner.kind}
                      className="h-4 w-4 shrink-0"
                    />
                  }
                  name={runner.name}
                  detail={runnerDetail(runner)}
                  selected={agent.harnessClientId === runner.id}
                />
              </DropdownMenuItem>
            ))}
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
