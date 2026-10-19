/**
 * An "Install in AgentArea" link from outside the app (the landing's skill
 * pages): `/skills/import?github=<url>`. It lands on the create-skill form with
 * the GitHub source picked and the URL filled in; the person still submits it.
 */

export const SKILL_IMPORT_QUERY_PARAM = "github";

const GITHUB_ORIGIN = "https://github.com";
const MAX_URL_LENGTH = 2048;

const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const REPO = /^[A-Za-z0-9._-]{1,100}$/;
const REF = /^[A-Za-z0-9._-]{1,255}$/;

/**
 * The URL when it names a skill on github.com, else null:
 * `https://github.com/{owner}/{repo}` or `.../{tree|blob}/{ref}[/{path}]`.
 * Only https on the exact host, no credentials, port, query or fragment. The
 * result is rebuilt from the parsed path, so nothing else of the input survives.
 */
export function parseGithubSkillUrl(
  raw: string | null | undefined
): string | null {
  if (!raw || raw.length > MAX_URL_LENGTH) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (
    url.protocol !== "https:" ||
    url.hostname !== "github.com" ||
    url.port ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    return null;
  }

  const segments = url.pathname.replace(/^\/|\/$/g, "").split("/");
  const [owner, repo, kind, ref, ...path] = segments;
  if (!owner || !OWNER.test(owner)) return null;
  if (!repo || !REPO.test(repo) || repo === "." || repo === "..") return null;
  if (kind === undefined) return `${GITHUB_ORIGIN}/${owner}/${repo}`;
  if (kind !== "tree" && kind !== "blob") return null;
  if (!ref || !REF.test(ref)) return null;
  if (path.some((segment) => !segment)) return null;

  return [GITHUB_ORIGIN, owner, repo, kind, ref, ...path].join("/");
}
