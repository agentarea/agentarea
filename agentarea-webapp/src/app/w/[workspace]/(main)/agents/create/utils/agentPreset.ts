import type {
  AgentPresetResponse,
  ModelInstanceResponse,
  TriggerSpec,
} from "@/api/client/types.gen";
import { modelNameMatchesPreferred } from "@/app/w/[workspace]/(main)/bundles/components/catalog-data";
import { toToolsConfig } from "../../shared/agentContract";
import type { AgentFormValues, AgentSkill } from "../types";

export type PresetFormValues = {
  /** Absent for the Empty preset, which leaves the instruction alone. */
  instruction?: string;
  tools_config: AgentFormValues["tools_config"];
  skills: AgentSkill[];
  triggers: TriggerSpec[];
};

/** What applying a preset replaces in the create form; `null` is Empty. */
export function presetFormValues(
  preset: AgentPresetResponse | null
): PresetFormValues {
  if (!preset) {
    return { tools_config: toToolsConfig([]), skills: [], triggers: [] };
  }
  return {
    instruction: preset.instruction ?? "",
    tools_config: toToolsConfig(preset.tools),
    // Catalog skill ids: the backend installs them when the agent is created
    skills: preset.skills.map((skill) => ({
      id: skill.id,
      name: skill.name,
      description: skill.description ?? null,
    })),
    triggers: preset.triggers.map((trigger) => ({ ...trigger })),
  };
}

/** First active workspace model matching the preset's preferences, in order. */
export function preferredModelId(
  preset: Pick<AgentPresetResponse, "preferred_models">,
  modelInstances: Pick<ModelInstanceResponse, "id" | "model_name" | "is_active">[]
): string | null {
  for (const preferred of preset.preferred_models ?? []) {
    const match = modelInstances.find(
      (instance) =>
        instance.is_active &&
        modelNameMatchesPreferred(instance.model_name ?? "", preferred)
    );
    if (match) return match.id;
  }
  return null;
}
