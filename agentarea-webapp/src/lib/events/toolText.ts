// Turns textual tool output into the Markdown worth showing.

const SKILL_WRAPPER =
  /^\s*<skill_content\b[^>]*>\s*([\s\S]*?)\s*(?:<\/skill_content>\s*)?$/;
const FRONTMATTER = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

/**
 * A skill activation returns the skill file wrapped in <skill_content>; its
 * YAML frontmatter, read as Markdown, becomes a giant heading. Shows the body.
 */
export function readableToolText(text: string): string {
  const wrapped = SKILL_WRAPPER.exec(text);
  if (!wrapped) return text;
  return wrapped[1].replace(FRONTMATTER, "").trimStart();
}

const BLOCK_START = /^\s*(?:[-*+]\s|\d+[.)]\s|#|>|\||```)/;

/**
 * Joins the lines a Markdown paragraph was wrapped into, as a renderer would:
 * blank lines, list items, headings, quotes, tables and code fences stay.
 */
export function unwrapSoftBreaks(text: string): string {
  const lines = text.split("\n");
  const out: string[] = [];
  let fenced = false;
  for (const line of lines) {
    const prev = out[out.length - 1];
    if (line.trimStart().startsWith("```")) fenced = !fenced;
    const joins =
      !fenced &&
      prev !== undefined &&
      prev.trim() !== "" &&
      line.trim() !== "" &&
      !BLOCK_START.test(line) &&
      !prev.trimStart().startsWith("```");
    if (joins) out[out.length - 1] = `${prev.trimEnd()} ${line.trim()}`;
    else out.push(line);
  }
  return out.join("\n");
}
