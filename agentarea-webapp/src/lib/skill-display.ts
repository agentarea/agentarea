export type SkillDisplayInput = {
  name: string;
  description?: string | null;
  source_url?: string | null;
};

export type SkillDisplay = {
  /** The skill's own name, readable: "action-creator" → "Action creator". */
  title: string;
  /** Where it came from — the GitHub repo, else its description. */
  subtitle: string | null;
  /** Short content hash an imported skill carries, told apart from its twins. */
  ref: string | null;
};

const HASH = /^[0-9a-f]{6,}$/i;
const GITHUB_REPO = /github\.com\/([^/\s]+)\/([^/\s#?]+)/i;

/**
 * How a skill reads in a list.
 *
 * Imported skills are named `<skill>--<owner>-<repo>--<hash>`: the source
 * spelled into the name, and the part a person would call the skill buried at
 * the front of a long slug. Two imports of one skill at different commits
 * differ only in that hash. This takes the name apart — the skill's name as the
 * title, the repo from its URL underneath, the hash kept short so twins stay
 * distinguishable. A name written by a person passes through tidied, not cut.
 */
export function skillDisplay(skill: SkillDisplayInput): SkillDisplay {
  const parts = skill.name.split("--");
  const last = parts[parts.length - 1];
  const ref = parts.length >= 3 && HASH.test(last) ? last.slice(0, 6) : null;

  const repo = skill.source_url?.match(GITHUB_REPO);
  const subtitle = repo
    ? `${repo[1]}/${repo[2].replace(/\.git$/i, "")}`
    : skill.description?.trim() || null;

  return { title: humanize(parts[0]) || skill.name, subtitle, ref };
}

function humanize(slug: string): string {
  const words = slug.replace(/[-_]+/g, " ").trim().replace(/\s+/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
