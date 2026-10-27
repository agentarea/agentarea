#!/usr/bin/env python3
"""Print the "## Highlights" and "## Главное" sections of a release PR body.

release-prepare puts both sections, empty, into the release PR; whoever merges
it fills them in. release-publish pipes the merged PR's body through this
script and puts the result at the top of the GitHub Release, where
agentarea.ai/changelog reads it from. A section with no bullet items is left
out, so an unfilled template adds nothing to the release.

Usage: gh pr view ... --json body -q .body | python3 scripts/release_highlights.py
"""

import re
import sys

HEADINGS = ("Highlights", "Главное")


def extract(body: str) -> str:
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    sections: list[str] = []
    current: list[str] | None = None
    for line in body.splitlines():
        if re.match(r"^#{1,6}\s", line):
            # Any heading ends the section; only an H2 we know starts one.
            if current is not None:
                sections.append("\n".join(current))
            name = line[3:].split(":", 1)[0].strip() if line.startswith("## ") else ""
            current = [line.rstrip()] if name in HEADINGS else None
        elif current is not None:
            current.append(line.rstrip())
    if current is not None:
        sections.append("\n".join(current))

    kept = []
    for section in sections:
        heading, *rest = section.split("\n")
        items = [line for line in rest if re.match(r"^\s*[-*]\s+\S", line)]
        if items:
            kept.append("\n".join([heading, "", *items]))
    return "\n\n".join(kept)


if __name__ == "__main__":
    out = extract(sys.stdin.read())
    if out:
        print(out)
