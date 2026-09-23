import { describe, expect, it } from "vitest";
import type { A2UIAction } from "../types";
import {
  buildButtonAction,
  resolvePointer,
  selectedChoices,
  setBoundValue,
  toggleChoice,
} from "./a2uiForm";

function model(): Record<string, unknown> {
  return {
    person: { name: "Ada" },
    approved: false,
    score: 2,
    choices: ["one"],
  };
}

const submit: A2UIAction = {
  event: {
    name: "submit",
    context: {
      name: { path: "/person/name" },
      approved: { path: "/approved" },
      score: { path: "/score" },
      choices: { path: "/choices" },
      source: "review-form",
    },
  },
};

describe("A2UI form delivery", () => {
  it("sends edited bound values, not the original model", () => {
    const original = model();
    let edited = setBoundValue(original, "/person/name", "Grace");
    edited = setBoundValue(edited, "/approved", true);
    edited = setBoundValue(edited, "/score", 7);
    edited = setBoundValue(
      edited,
      "/choices",
      toggleChoice(
        selectedChoices(resolvePointer(edited, "/choices")),
        "two",
        true
      )
    );

    expect(
      buildButtonAction({ action: submit, dataModel: edited, disabled: false })
    ).toEqual({
      action: submit,
      context: {
        name: "Grace",
        approved: true,
        score: 7,
        choices: ["one", "two"],
        source: "review-form",
      },
    });
    expect(original).toEqual(model());
  });

  it("does not accept actions from a closed form", () => {
    expect(
      buildButtonAction({ action: submit, dataModel: model(), disabled: true })
    ).toBeNull();
  });

  it("has nothing to send for a button without an action", () => {
    expect(
      buildButtonAction({
        action: undefined,
        dataModel: model(),
        disabled: false,
      })
    ).toBeNull();
  });

  it("resolves an unbound path to undefined instead of throwing", () => {
    expect(resolvePointer(model(), "/person/age")).toBeUndefined();
    expect(resolvePointer(model(), "/score/deeper")).toBeUndefined();
    expect(resolvePointer({ "a/b": 1 }, "/a~1b")).toBe(1);
  });
});

describe("toggleChoice", () => {
  it("adds and removes options in a multiple selection", () => {
    expect(toggleChoice(["one"], "two", true)).toEqual(["one", "two"]);
    expect(toggleChoice(["one", "two"], "one", true)).toEqual(["two"]);
  });

  it("replaces the pick in a single selection", () => {
    expect(toggleChoice(["one"], "two", false)).toEqual(["two"]);
  });
});

describe("selectedChoices", () => {
  it("reads a bound value as a list of picks", () => {
    expect(selectedChoices(["a", "b"])).toEqual(["a", "b"]);
    expect(selectedChoices("a")).toEqual(["a"]);
    expect(selectedChoices(undefined)).toEqual([]);
  });
});
