import type {
  AgentClientSummary,
  ClientResponse,
} from "@/api/client/types.gen";

export const ON_PLATFORM = "platform";

/** The model a platform run of the agent calls. */
export type PlatformModel = {
  name: string;
  provider: string | null;
  iconUrl: string | null;
};

type Runner = Pick<ClientResponse, "id" | "kind" | "name" | "default_model"> & {
  online?: boolean;
};

/** Where a run can go: the platform loop on the agent's model, or a Codex / Claude Code client's runner. */
export type RunTarget =
  | ({ id: typeof ON_PLATFORM; on: "platform" } & PlatformModel)
  | {
      id: string;
      on: "runner";
      kind: string;
      name: string;
      model: string | null;
      online: boolean;
    };

const runnerTarget = (client: Runner): RunTarget => ({
  id: client.id,
  on: "runner",
  kind: client.kind,
  name: client.name,
  model: client.default_model ?? null,
  online: client.online ?? false,
});

const platformTarget = (model: PlatformModel): RunTarget => ({
  id: ON_PLATFORM,
  on: "platform",
  ...model,
});

/** Where an agent's runs may go, and where they go unless a run names another. */
export type RunTargets = { targets: RunTarget[]; agentTarget: string | null };

/**
 * The places a run of the agent may go, the agent's own first, and which one
 * it goes to unless the run names another. The platform is offered only to an
 * agent that runs there, since a runner agent has no platform model.
 */
export function runTargets(
  agent: { model: PlatformModel | null; client: AgentClientSummary | null },
  runners: Runner[]
): RunTargets {
  const own = agent.client;
  const others = runners.filter((client) => client.id !== own?.id);
  const targets: RunTarget[] = [
    ...(own ? [runnerTarget(own)] : []),
    ...(!own && agent.model ? [platformTarget(agent.model)] : []),
    ...others.map(runnerTarget),
  ];
  return {
    targets,
    agentTarget: own?.id ?? (agent.model ? ON_PLATFORM : null),
  };
}
