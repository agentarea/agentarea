import React from "react";
import { MessageMarkdown } from "@/components/Chat/MessageMarkdown";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { cn } from "@/lib/utils";
import { stripA2UIFromStreamingContent } from "../a2ui";
import type { Part } from "../contract";

// The event log keeps a long thought as this marker; there is nothing to read.
const OMITTED = /^\[omitted from event log: \d+ units\]$/;

/**
 * The model's thought before its next step, as muted text: a few lines, the
 * rest on click. A thought still streaming shows whole.
 */
function Thought({ text, live }: { text: string; live: boolean }) {
  const [open, setOpen] = React.useState(false);
  const whole = live || open;
  return (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      aria-expanded={whole}
      className={cn(
        "mb-1 block w-full whitespace-pre-wrap text-left text-xs leading-5 text-muted-foreground transition-colors hover:text-foreground",
        !whole && "line-clamp-3"
      )}
    >
      {text.trim()}
    </button>
  );
}

/** Renders an llm part: streamed chunk text or the final assistant content. */
export const TextPart: React.FC<{ part: Part }> = ({ part }) => {
  const { data } = part;
  const raw =
    typeof data.content === "string"
      ? data.content
      : typeof data.chunk === "string"
        ? data.chunk
        : "";
  // Agents embed A2UI surface JSON after a delimiter in the streamed text; the
  // surface renders as its own part, so never show the raw markup here.
  const content = stripA2UIFromStreamingContent(raw);
  const streaming =
    part.eventType === "llm.call.chunk" && data.is_final !== true;
  const thinking = typeof data.thinking === "string" ? data.thinking : "";
  const failed = part.eventType === "llm.call.failed";
  const failure =
    typeof data.error === "string" && data.error.trim()
      ? data.error.trim()
      : "LLM call failed";

  return (
    <div className="min-w-0 px-2">
      {thinking && !OMITTED.test(thinking) && (
        <Thought text={thinking} live={streaming && !content} />
      )}
      {failed ? (
        <StatusIndicator kind="failed">{failure}</StatusIndicator>
      ) : streaming && !content ? (
        <StatusIndicator kind="running">Thinking</StatusIndicator>
      ) : null}
      {content ? (
        <MessageMarkdown content={content} isStreaming={streaming} />
      ) : null}
    </div>
  );
};

export default TextPart;
