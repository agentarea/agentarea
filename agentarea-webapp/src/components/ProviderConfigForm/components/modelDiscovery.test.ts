import { describe, expect, it } from "vitest";
import type { ModelSpec } from "@/types/provider";
import { filterModelsByDiscovery } from "./modelDiscovery";

const model = (id: string, modelName: string): ModelSpec =>
  ({
    id,
    model_name: modelName,
  }) as ModelSpec;

describe("filterModelsByDiscovery", () => {
  it("keeps only models returned by the current provider discovery", () => {
    const availableModels = [
      model("current", "provider/current-model"),
      model("stale", "provider/stale-model"),
    ];

    expect(
      filterModelsByDiscovery(
        availableModels,
        new Set(["provider/current-model"])
      )
    ).toEqual([availableModels[0]]);
  });

  it("returns an empty list when the provider reports no matching models", () => {
    const availableModels = [model("stale", "provider/stale-model")];

    expect(filterModelsByDiscovery(availableModels, new Set())).toEqual([]);
  });

  it("leaves the registry list unchanged before discovery", () => {
    const availableModels = [model("existing", "provider/existing-model")];

    expect(filterModelsByDiscovery(availableModels, null)).toBe(
      availableModels
    );
  });
});
