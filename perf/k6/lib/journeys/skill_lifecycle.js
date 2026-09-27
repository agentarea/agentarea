// Create -> read -> delete a small skill. No external calls: content is
// plain markdown, no frontmatter required (SkillCreateRequest.name overrides
// whatever the parser would derive from the content itself).
import { check, group } from "k6";
import { BASE_URL, WORKSPACE } from "../config.js";
import { get, postJson, del } from "../http.js";
import { assertWriteAllowed } from "./guard.js";
import { resourceName } from "./naming.js";
import { tag } from "./tags.js";

const ws = (suffix) => `${BASE_URL}/v1/workspaces/${encodeURIComponent(WORKSPACE)}${suffix}`;

// Exported separately so agent_lifecycle.js can create a throwaway skill to
// attach without duplicating the create call.
export function createSkill() {
  const name = resourceName("skill");
  const res = postJson(
    ws("/skills"),
    { name, content: `# ${name}\n\nDisposable skill created by the k6 perf suite.` },
    "create",
    tag("skill_lifecycle", "create")
  );
  check(res, { "skill create -> 201/200": (r) => r.status === 201 || r.status === 200 });
  return res.status < 300 ? res.json() : null;
}

export function deleteSkill(id) {
  if (!id) return;
  const res = del(ws(`/skills/${id}`), "delete", tag("skill_lifecycle", "delete"));
  check(res, { "skill delete -> 204/200/404": (r) => [200, 204, 404].includes(r.status) });
}

export const skillLifecycle = {
  name: "skill_lifecycle",
  run: () => {
    assertWriteAllowed("skill_lifecycle");
    group("journey: skill_lifecycle", () => {
      const skill = createSkill();
      if (!skill || !skill.id) return;

      const readRes = get(ws(`/skills/${skill.id}`), "read", tag("skill_lifecycle", "read"));
      check(readRes, { "skill read -> 200": (r) => r.status === 200 });

      deleteSkill(skill.id);
    });
  },
};
