import type {
  AgentClientSummary,
  ClientResponse,
} from "@/api/client/types.gen";

/** A chat model of the workspace a platform agent runs on. */
export type PlatformModel = {
  id: string;
  name: string;
  provider: string | null;
  iconUrl: string | null;
};

/** A Codex or Claude Code client: a harness a task can be given to directly. */
export type Runner = Pick<
  ClientResponse,
  "id" | "kind" | "name" | "default_model"
> & {
  online?: boolean;
};

/** The workspace's models and harnesses, to say where each agent runs and to offer the harnesses. */
export type RunOptions = { models: PlatformModel[]; runners: Runner[] };

export type RunsOn =
  | { on: "platform"; model: PlatformModel }
  | { on: "runner"; runner: Runner };

/** Where the agent's tasks run: its model on the platform, or its harness. */
export function runsOn(
  agent: { modelId: string | null; client: AgentClientSummary | null },
  options: RunOptions
): RunsOn | null {
  const own = agent.client;
  if (own) {
    return {
      on: "runner",
      runner: options.runners.find((runner) => runner.id === own.id) ?? own,
    };
  }
  const model = options.models.find((m) => m.id === agent.modelId);
  return model ? { on: "platform", model } : null;
}
