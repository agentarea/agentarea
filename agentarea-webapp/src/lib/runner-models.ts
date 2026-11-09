import type { ClientResponse } from "@/api/client/types.gen";

/** A model a client's runner reported, with the reasoning levels its CLI takes. */
export type RunnerModel = {
  name: string;
  reasoningLevels: string[];
  defaultReasoning: string | null;
};

const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];

export function runnerModels(
  client: Pick<ClientResponse, "models">
): RunnerModel[] {
  return (client.models ?? []).flatMap((model) =>
    typeof model.name === "string"
      ? [
          {
            name: model.name,
            reasoningLevels: strings(model.reasoning_levels),
            defaultReasoning:
              typeof model.default_reasoning === "string"
                ? model.default_reasoning
                : null,
          },
        ]
      : []
  );
}

export function runnerModel(
  client: Pick<ClientResponse, "models">,
  name: string | null | undefined
): RunnerModel | null {
  return runnerModels(client).find((model) => model.name === name) ?? null;
}

/** The level an agent keeps on this model: "" (the model's default) once the model does not offer it. */
export function offeredLevel(
  model: RunnerModel | null,
  level: string | null | undefined
): string {
  return level && model?.reasoningLevels.includes(level) ? level : "";
}

/** "gpt-6.1-terra · high", or the model alone when the agent keeps the model's default. */
export function withReasoning(
  model: string | null | undefined,
  level: string | null | undefined
): string | null {
  if (!model) return null;
  return level ? `${model} · ${level}` : model;
}
