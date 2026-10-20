/**
 * A one-line preview of a markdown string: the words without the markup, for
 * a clamped table cell. Code keeps its text, links keep their label, images
 * and HTML tags go, list items are kept apart with a middle dot, and every
 * line break becomes a space.
 */
export function markdownToPlainText(markdown: string): string {
  const unlinked = markdown
    .replace(/```[^\n]*\n([\s\S]*?)```/g, "$1") // fenced code: keep the code
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "") // images
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1"); // links: keep the label
  return stripTags(unlinked)
    .replace(/`([^`]*)`/g, "$1") // inline code
    .replace(/(\*\*|__)(.+?)\1/g, "$2") // bold
    .replace(/(^|[^\w*])[*_]([^*_\n]+)[*_](?=[^\w*]|$)/g, "$1$2") // italic
    .replace(/~~(.+?)~~/g, "$1") // strikethrough
    .replace(/^\s{0,3}#{1,6}\s+/gm, "") // headings
    .replace(/^\s{0,3}>\s?/gm, "") // blockquotes
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, "· ") // list items stay apart
    .replace(/\s+/g, " ")
    .replace(/^· /, "")
    .trim();
}

/**
 * Inline HTML without its tags, and without any angle bracket left over. One
 * pass is not enough: removing a tag can join the halves of a nested one
 * ("<scr<script>ipt>") into a new tag, so it repeats until none is found.
 */
function stripTags(text: string): string {
  let current = text;
  let previous: string;
  do {
    previous = current;
    current = current.replace(/<[^<>]*>/g, "");
  } while (current !== previous);
  return current.replace(/[<>]/g, "");
}

/**
 * The opening of a markdown text as plain words: its first paragraph, stopping
 * at the first blank line or list. A table cell shows this; the rest is what
 * opening the row is for.
 */
export function markdownSummary(markdown: string): string {
  return markdownToPlainText(splitMarkdownSummary(markdown).summary);
}

/**
 * A markdown text cut after its first paragraph (at a blank line or a list),
 * both halves still markdown: a cell renders the summary, the open row the rest.
 */
export function splitMarkdownSummary(markdown: string): { summary: string; rest: string } {
  const text = markdown.trim();
  const end = text.search(/\n\s*\n|\n\s*(?:[-*+]|\d+[.)])\s+/);
  return end === -1
    ? { summary: text, rest: "" }
    : { summary: text.slice(0, end), rest: text.slice(end).trim() };
}

/**
 * The markdown a cell's summary leaves out: what follows the first paragraph.
 * When that paragraph itself is too long for the cell, the whole text, since
 * the cell cut it short.
 */
export function markdownBeyondSummary(markdown: string, previewChars = 120): string {
  const { summary, rest } = splitMarkdownSummary(markdown);
  return markdownToPlainText(summary).length > previewChars ? markdown.trim() : rest;
}

/**
 * Whether opening the full markdown shows more than its summary: more text
 * follows the first paragraph, or that paragraph is longer than a clamped cell
 * shows. Formatting alone does not count; it would repeat the same words.
 */
export function markdownExceedsPreview(
  markdown: string,
  previewChars = 120
): boolean {
  return markdownBeyondSummary(markdown, previewChars) !== "";
}
