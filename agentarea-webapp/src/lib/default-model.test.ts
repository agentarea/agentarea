import { describe, expect, it } from "vitest";
import {
  defaultModelId,
  withDefaultModel,
  withPresetModel,
  type ModelSelection,
} from "./default-model";

const platform = (
  id: string,
  model_name: string,
  tags: string[] = [],
  is_active = true
) => ({ id, model_name, tags, is_active, managed_by: "platform" });
const own = (id: string, model_name: string, tags: string[] = []) => ({
  id,
  model_name,
  tags,
  is_active: true,
  managed_by: null,
});

describe("defaultModelId", () => {
  it("picks the platform model tagged default", () => {
    const instances = [
      platform("a", "deepseek-v3", ["fast"]),
      platform("k", "kimi-k2.6", ["default", "reasoning"]),
    ];

    expect(defaultModelId(instances)).toBe("k");
  });

  it("leaves the picker empty when no platform model is tagged", () => {
    expect(defaultModelId([platform("a", "deepseek-v3")])).toBeNull();
  });

  it("never preselects a model on the workspace's own key", () => {
    expect(defaultModelId([own("o", "gpt-4o", ["default"])])).toBeNull();
  });

  it("skips an inactive default", () => {
    expect(
      defaultModelId([platform("k", "kimi-k2.6", ["default"], false)])
    ).toBeNull();
  });

  it("settles several defaults by name, so every page agrees", () => {
    const instances = [
      platform("z", "qwen-3", ["default"]),
      platform("a", "deepseek-v3", ["default"]),
    ];

    expect(defaultModelId(instances)).toBe("a");
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
