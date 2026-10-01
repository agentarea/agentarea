import type { ModelInstanceResponse } from "@/api/client/types.gen";

type Instance = Pick<
  ModelInstanceResponse,
  "id" | "model_name" | "is_active" | "managed_by" | "tags"
>;

/** The tag that marks the platform model a new agent starts on. */
export const DEFAULT_MODEL_TAG = "default";

/**
 * The model a new agent starts on: the active platform model tagged `default`.
 *
 * The tag is data the operator writes from the LLMProviderConfig resource, so the
 * default moves with an edit in git, not a redeploy. Only platform models count:
 * preselecting one on the workspace's own key would spend the customer's provider
 * credit on a choice they did not make. Several tagged is a mistake the operator
 * warns about; the first by name wins so every page agrees. `null` when none is
 * tagged, which leaves the picker empty rather than guessing.
 */
export function defaultModelId(instances: Instance[]): string | null {
  const [first] = instances
    .filter(
      (instance) =>
        instance.is_active &&
        instance.managed_by === "platform" &&
        (instance.tags ?? []).includes(DEFAULT_MODEL_TAG)
    )
    .sort(
      (a, b) =>
        (a.model_name ?? "").localeCompare(b.model_name ?? "") ||
        a.id.localeCompare(b.id)
    );
  return first?.id ?? null;
}

/**
 * Who put the current model on the agent form, which decides who may replace it.
 *
 * - `none`: nobody, the field is empty.
 * - `default`: the platform default; a preset's preferred model replaces it.
 * - `preset`: the applied preset; another preset replaces it.
 * - `chosen`: the user, or the agent being edited already had one. Never replaced.
 */
export type ModelSource = "none" | "default" | "preset" | "chosen";

export type ModelSelection = { modelId: string; source: ModelSource };

/** The platform default arriving fills only a field nobody has set. */
export function withDefaultModel(
  current: ModelSelection,
  defaultId: string | null
): ModelSelection {
  if (current.source !== "none" || !defaultId) return current;
  return { modelId: defaultId, source: "default" };
}

/**
 * Applying a preset: its preferred model wins over the platform default, and
 * switching to a preset without one drops the previous preset's model back to
 * the default rather than keeping a choice that came with a preset no longer
 * applied.
 */
export function withPresetModel(
  current: ModelSelection,
  presetModelId: string | null,
  defaultId: string | null
): ModelSelection {
  if (current.source === "chosen") return current;
  if (presetModelId) return { modelId: presetModelId, source: "preset" };
  if (current.source === "preset") {
    return defaultId
      ? { modelId: defaultId, source: "default" }
      : { modelId: "", source: "none" };
  }
  return current;
}
