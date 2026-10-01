import { describe, expect, it } from "vitest";
import {
  defaultModelId,
  withDefaultModel,
  withPresetModel,
  type ModelSelection,
} from "./default-model";

const platform = (id: string, model_name: string, is_active = true) => ({
  id,
  model_name,
  is_active,
  managed_by: "platform",
});
const own = (id: string, model_name: string) => ({
  id,
  model_name,
  is_active: true,
  managed_by: null,
});

describe("defaultModelId", () => {
  it("picks the deployment's preferred platform model", () => {
    const instances = [
      platform("a", "deepseek-v3"),
      platform("k", "kimi-k2.6"),
      own("o", "gpt-4o"),
    ];

    expect(defaultModelId(instances, "kimi-k2.6")).toBe("k");
  });

  it("falls to the first platform model by name when the preferred one is absent", () => {
    const instances = [platform("z", "qwen-3"), platform("a", "deepseek-v3")];

    expect(defaultModelId(instances, "kimi-k2.6")).toBe("a");
    expect(defaultModelId(instances, "")).toBe("a");
  });

  it("never preselects a model on the workspace's own key", () => {
    expect(defaultModelId([own("o", "kimi-k2.6")], "kimi-k2.6")).toBeNull();
  });

  it("skips an inactive platform model", () => {
    const instances = [
      platform("k", "kimi-k2.6", false),
      platform("q", "qwen-3"),
    ];

    expect(defaultModelId(instances, "kimi-k2.6")).toBe("q");
  });
});

describe("model precedence on the agent form", () => {
  const none: ModelSelection = { modelId: "", source: "none" };

  it("the platform default fills only an empty field", () => {
    expect(withDefaultModel(none, "k")).toEqual({
      modelId: "k",
      source: "default",
    });
    const preset: ModelSelection = { modelId: "p", source: "preset" };
    expect(withDefaultModel(preset, "k")).toBe(preset);
  });

  it("a preset's model replaces the platform default", () => {
    const afterDefault = withDefaultModel(none, "k");

    expect(withPresetModel(afterDefault, "p", "k")).toEqual({
      modelId: "p",
      source: "preset",
    });
  });

  it("a preset without a model returns the previous preset's choice to the default", () => {
    const fromPreset: ModelSelection = { modelId: "p", source: "preset" };

    expect(withPresetModel(fromPreset, null, "k")).toEqual({
      modelId: "k",
      source: "default",
    });
    expect(withPresetModel(fromPreset, null, null)).toEqual(none);
  });

  it("the user's choice survives both the default and a preset", () => {
    const chosen: ModelSelection = { modelId: "u", source: "chosen" };

    expect(withDefaultModel(chosen, "k")).toBe(chosen);
    expect(withPresetModel(chosen, "p", "k")).toBe(chosen);
  });
});
