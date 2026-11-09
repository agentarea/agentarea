import { describe, expect, it } from "vitest";
import { perMillionToPerToken, toModelSpecCreate } from "./manualModelSpec";

describe("perMillionToPerToken", () => {
  it("shifts a price per million tokens to a price per token in plain decimals", () => {
    expect(perMillionToPerToken("2.5")).toBe("0.0000025");
    expect(perMillionToPerToken("0.15")).toBe("0.00000015");
    expect(perMillionToPerToken("12")).toBe("0.000012");
    expect(perMillionToPerToken("1500000")).toBe("1.5");
  });

  it("keeps zero as an explicit free price", () => {
    expect(perMillionToPerToken("0")).toBe("0");
  });

  it("reads a blank field as no price", () => {
    expect(perMillionToPerToken("")).toBeNull();
    expect(perMillionToPerToken("  ")).toBeNull();
  });
});

describe("toModelSpecCreate", () => {
  it("maps the form to the contract with the price left unknown when not entered", () => {
    expect(
      toModelSpecCreate("spec-1", {
        model_name: " llama3.1:8b ",
        context_window: "131072",
        input_per_million: "",
        output_per_million: "",
      })
    ).toEqual({
      provider_spec_id: "spec-1",
      model_name: "llama3.1:8b",
      display_name: "llama3.1:8b",
      context_window: 131072,
      input_cost_per_token: null,
      output_cost_per_token: null,
    });
  });
});
