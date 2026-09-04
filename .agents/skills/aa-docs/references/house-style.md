# House style and audit checklist

## Voice

Write for a platform engineer who is competent, busy, and skeptical. They have
deployed things like this before and have been burned by docs that oversold.

- **Second person, present tense, active voice.** "The scheduler retries the
  task", not "the task will be retried by the scheduler".
- **Lead with the answer.** The first sentence of every page and every section
  says the thing. Context comes after.
- **Name the tradeoff.** Every architectural claim carries a cost. Stating it is
  what makes the rest credible.
- **State limits plainly.** Especially for sandbox isolation and governance
  enforcement. A reader making a security decision from a page that omits the
  limits has been misled by omission.
- **No "simply", "just", "easy", "obviously", "powerful", "seamless".** If a
  step is easy the reader will notice without being told; if it is not, the word
  reads as contempt.
- **No unearned superlatives.** "Production-ready", "enterprise-grade" and
  "blazing fast" are claims. Either back them with a number or cut them.
- **Numbers over adjectives.** "~1.3 s activation vs 8-15 s cold start" is worth
  more than "fast". If you cite a number, cite where it was measured.

## Formatting

- Sentence case in headings. "Run a command in a sandbox".
- One H1 per page, matching `title` in frontmatter.
- Code blocks are complete and runnable. No `...`, no invented placeholders
  where a real value would do. Tag the language.
- Long output goes in a collapsible block, not inline.
- Tables for parameters, prose for reasoning. Never prose for parameters.
- Link on the noun, not on "here" or "this page".
- Diagrams: Mermaid, and only when the relationship is genuinely hard to state
  in a sentence. Three of the current pages open with the same architecture
  diagram, which means none of them needed it.

## Emoji

Current docs use emoji heavily in headings and card titles. The repo bans emoji
in source code. Docs are not source, so this is a live decision rather than a
settled rule — but the benchmarked sites (Stripe, Vault, Tailscale, Temporal,
Cloudflare) use none, and emoji in headings degrade search results and screen
readers. Recommendation: drop them from headings and body, keep them out of new
pages, and raise it once rather than relitigating per page.

## Terminology

Pick one term and never alternate. Current inconsistencies to settle:

| Use | Not |
|---|---|
| workspace | tenant, org (except where OpenFGA types are being described) |
| task | job, run, execution (reserve "execution" for the Temporal layer) |
| sandbox session | sandbox instance, container |
| MCP server instance | MCP instance, MCP container |
| tool call | tool invocation, function call |
| ReBAC | RBAC — the authorization model here is relationship-based; calling it RBAC is wrong, not loose |

New terms go in `reference/glossary` at the moment they are first used.

## Accuracy rules

- **Ground every claim in code.** Open the file. `libs/governance/` for policy,
  `internal/sandbox*/` for the sandbox, the OpenAPI spec for endpoints.
- **Never document intent.** If the code does not do it yet, it does not go in
  `docs/`. It goes in the roadmap.
- **Do not hand-write anything a generator can produce** — endpoint tables,
  parameter lists, env var lists. Hand-written copies drift and drift silently.
- **Re-verify on edit.** When touching a page older than one release, check its
  claims still hold before shipping the edit.

## Audit checklist

Run these against `docs/`. Each is a real defect class found in the current tree.

```bash
cd docs

# 1. Orphans on disk, and 2. navigation entries with no file.
# Collect only `pages` values — walking every string also picks up group titles
# and icon names, which makes both checks lie.
python3 - <<'EOF'
import json, glob, os
nav = set()
def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == 'pages':
                for p in v:
                    if isinstance(p, str): nav.add(p)
                    else: walk(p)
            else: walk(v)
    elif isinstance(o, list): [walk(v) for v in o]
walk(json.load(open('docs.json'))['navigation'])
for p in sorted({f[:-3] for f in glob.glob('*.md')} - nav):
    print(f"ORPHAN  {p}.md ({os.path.getsize(p+'.md')//1024}K)")
for n in sorted(nav):
    if not any(os.path.exists(n + e) for e in ('.md', '.mdx')):
        print(f"MISSING {n} (in nav, no file)")
EOF

# 3. Duplicate .md/.mdx pairs
for f in *.mdx; do b="${f%.mdx}.md"; [ -f "$b" ] && \
  { diff -q "$f" "$b" >/dev/null && echo "DUPLICATE $f == $b" || echo "DIVERGED  $f != $b"; }; done

# 4. Oversized pages — almost always mixed genres
find . -maxdepth 2 -name '*.md' -size +8k -not -path './node_modules/*' | xargs ls -lhS 2>/dev/null

# 5. Missing frontmatter type
grep -L "^type:" *.md

# 6. Banned words
grep -rniE "\b(simply|just |easy|obviously|seamless|blazing)\b" --include="*.md" . | grep -v node_modules

# 7. Endpoint citations — every `/v1/...` in prose must exist in the spec.
# This has caught real defects twice: a hand-written reference wrong on 9 of 11
# paths, and an author citing `/v1/mcp-proxy`, which is an OpenAPI TAG name and
# not a route (the real one is /v1/mcp/{instance_id}/mcp).
python3 - <<'EOF'
import glob, re, json, os
spec = json.load(open('api-reference/openapi.json'))
norm = lambda p: re.sub(r'\{[^}]+\}', '{}', p.rstrip('/'))
real = {norm(p) for p in spec['paths']}
prefixes = {p.rsplit('/', 1)[0] for p in real}          # prefix citations are legitimate
for f in sorted(glob.glob('**/*.md', recursive=True)):
    if 'node_modules' in f: continue
    for m in set(re.findall(r'`(?:GET|POST|PATCH|PUT|DELETE)?\s*(/v1/[^`\s]+)`', open(f).read())):
        n = norm(m.split('?')[0])
        if n in real or n in prefixes or any(r.startswith(n + '/') for r in real): continue
        print(f"UNRESOLVED {f}: {m}")
EOF

# 8. Structural validator
./validate-docs.sh
```

## When several agents write in parallel

Two failure modes, both observed:

- **Duplicate authorship.** Check whether a file already exists and is non-empty
  before writing it. If it does, do not overwrite — report the collision and
  switch to a verification pass over the existing pages instead. Independent
  authoring plus an independent audit beats two parallel drafts.
- **A correction sent to the wrong agent.** When a defect is found in a page,
  the fix goes to whoever is *still writing* in that area, not only to whoever
  owns the file it was found in. A correction sent to the auditor alone let the
  original author repeat the same wrong endpoint on a new page minutes later.

Then, per page, by hand:

- Does the page's actual content match its declared `type`?
- Does every guide have a `Verify` section?
- Does every architectural concept page state a tradeoff and a limit?
- Are there two pages that both claim to be the entry point?
- Does anything describe behaviour that the code no longer has?

Report as a table: `file | declared type | actual type | defect | action`. Do not
fix during an audit — produce the list first.
