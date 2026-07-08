import { test } from "@playwright/test";
import { functionalRequirements, requirementTitle } from "./requirements";

const runRealStack = process.env.PLAYWRIGHT_REAL_STACK === "1";
const todoRequirements = functionalRequirements.filter(
  (requirement) => requirement.status === "todo"
);

test.describe("functional requirements coverage backlog", () => {
  test.skip(
    !runRealStack,
    "Set PLAYWRIGHT_REAL_STACK=1 to run against a live stand"
  );

  for (const requirement of todoRequirements) {
    test.describe(`${requirement.id} ${requirement.title}`, () => {
      test.skip(
        requirementTitle(requirement.id, requirement.description),
        async () => {}
      );

      for (const criterion of requirement.acceptance) {
        test.skip(requirementTitle(requirement.id, criterion), async () => {});
      }
    });
  }
});
