import type { ModelInstanceResponse } from "@/api/client/types.gen";

type Instance = Pick<
  ModelInstanceResponse,
  "id" | "model_name" | "is_active" | "managed_by"
>;

/**
 * The model a new agent starts on: a platform model the workspace needs no key for.
 *
 * The deployment's preferred model (DEFAULT_PLATFORM_MODEL, a model_name) when it
 * is offered, else the first platform model by name so every page picks the same
 * one. Never a model on the workspace's own key: preselecting that would spend
 * the customer's provider credit on a choice they did not make. `null` when the
 * workspace has no platform model, which leaves the picker empty.
 */
export function defaultModelId(
  instances: Instance[],
  preferredName: string
): string | null {
  const platform = instances.filter(
    (instance) => instance.is_active && instance.managed_by === "platform"
  );
  const preferred = preferredName
    ? platform.find((instance) => instance.model_name === preferredName)
    : undefined;
  if (preferred) return preferred.id;
  const [first] = [...platform].sort(
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
