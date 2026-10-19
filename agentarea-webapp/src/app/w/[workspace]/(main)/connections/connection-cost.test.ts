import { describe, expect, it } from "vitest";
import { costToForm, emptyCostForm, formToCost } from "./connection-cost";

describe("a member-set connection cost", () => {
  it("is the connector's own when none is stored, and stores none back", () => {
    expect(costToForm(null).mode).toBe("connector");
    expect(formToCost(emptyCostForm())).toBeNull();
  });

  it("stores a price per call as a rate", () => {
    const form = {
      ...emptyCostForm("per_call"),
      amount: "0.01",
      currency: "usd",
    };

    expect(formToCost(form)).toEqual({
      source: "rate",
      unit: "call",
      rate: { amount: "0.01", currency: "USD" },
    });
  });

  it("counts units from an argument or from a path in the response", () => {
    const perPhrase = {
      ...emptyCostForm("per_unit"),
      amount: "0.002",
      unit: "phrase",
      quantity: "num_phrases",
    };
    const perPage = { ...perPhrase, unit: "page", quantity: "$.usage.pages" };

    expect(formToCost(perPhrase)).toMatchObject({
      unit: "phrase",
      rate: { quantity: { arg: "num_phrases" } },
    });
    expect(formToCost(perPage)).toMatchObject({
      rate: { quantity: { path: "$.usage.pages" } },
    });
  });

  it("reads the cost from a field of the response", () => {
    const form = {
      ...emptyCostForm("from_response"),
      path: "$.cost",
      currency: "USD",
    };

    expect(formToCost(form)).toEqual({
      source: "reported",
      reported: { path: "$.cost", currency: "USD" },
    });
  });

  it("edits what it stored", () => {
    const stored = [
      { source: "free" },
      {
        source: "rate",
        unit: "call",
        rate: { amount: "0.01", currency: "USD" },
      },
      {
        source: "rate",
        unit: "page",
        rate: { amount: "0.5", currency: "EUR", quantity: { path: "$.pages" } },
      },
      { source: "reported", reported: { path: "$.cost", currency: "EUR" } },
    ];

    for (const cost of stored) {
      expect(formToCost(costToForm(cost))).toEqual(cost);
    }
  });
});
