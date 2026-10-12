import { Fragment, type ReactNode } from "react";

/** Inline marks: `code`, **bold** and @mentions. Text only, never HTML. */
function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*|@[a-z][\w-]*)/gi).map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
      return (
        <code key={i} className="bg-secondary rounded px-1 py-px font-mono text-[0.9em]">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong key={i} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("@") && part.length > 1) {
      return (
        <span key={i} className="text-info font-medium">
          {part}
        </span>
      );
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/** The markdown subset issues use: paragraphs, headings, bullet and numbered lists, inline marks. */
export function Markdown({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/);
  return (
    <div className="flex flex-col gap-2.5 text-sm leading-relaxed">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        if (lines.every((line) => /^\s*[-*] /.test(line))) {
          return (
            <ul key={i} className="flex list-disc flex-col gap-1 pl-5">
              {lines.map((line, j) => (
                <li key={j}>{inline(line.replace(/^\s*[-*] /, ""))}</li>
              ))}
            </ul>
          );
        }
        if (lines.every((line) => /^\s*\d+\. /.test(line))) {
          return (
            <ol key={i} className="flex list-decimal flex-col gap-1 pl-5">
              {lines.map((line, j) => (
                <li key={j}>{inline(line.replace(/^\s*\d+\. /, ""))}</li>
              ))}
            </ol>
          );
        }
        const heading = /^#{1,6} (.*)$/.exec(lines[0]);
        if (heading && lines.length === 1) {
          return (
            <h4 key={i} className="mt-1 text-sm font-semibold">
              {inline(heading[1])}
            </h4>
          );
        }
        // A paragraph may run into a list without a blank line, as "**Title**\n- a\n- b".
        const listStart = lines.findIndex((line) => /^\s*[-*] /.test(line));
        if (listStart > 0 && lines.slice(listStart).every((line) => /^\s*[-*] /.test(line))) {
          return (
            <div key={i} className="flex flex-col gap-1">
              <p>{inline(lines.slice(0, listStart).join(" "))}</p>
              <ul className="flex list-disc flex-col gap-1 pl-5">
                {lines.slice(listStart).map((line, j) => (
                  <li key={j}>{inline(line.replace(/^\s*[-*] /, ""))}</li>
                ))}
              </ul>
            </div>
          );
        }
        return (
          <p key={i} className="whitespace-pre-line">
            {inline(block)}
          </p>
        );
      })}
    </div>
  );
}
