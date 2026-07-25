import type { ModelSpec } from "@/types/provider";

export function filterModelsByDiscovery(
  availableModels: ModelSpec[],
  discoveredModelNames: ReadonlySet<string> | null
): ModelSpec[] {
  if (discoveredModelNames === null) return availableModels;

  return availableModels.filter((model) =>
    discoveredModelNames.has(model.model_name)
  );
}
