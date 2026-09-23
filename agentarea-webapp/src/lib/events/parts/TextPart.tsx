import React from "react";
import { MessageMarkdown } from "@/components/Chat/MessageMarkdown";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { stripA2UIFromStreamingContent } from "../a2ui";
import type { Part } from "../contract";

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
  const streaming = part.eventType === "llm.call.chunk" && data.is_final !== true;
  const thinking = typeof data.thinking === "string" ? data.thinking : "";
  const failed = part.eventType === "llm.call.failed";

  return (
    <div className="min-w-0 px-2">
      {thinking && (
        <details open={streaming && !content} className="mb-2 text-xs text-muted-foreground">
          <summary className="cursor-pointer py-1 font-medium">Reasoning</summary>
          <div className="whitespace-pre-wrap py-1 leading-5">{thinking}</div>
        </details>
      )}
      {failed ? (
        <StatusIndicator tone="danger">LLM call failed</StatusIndicator>
      ) : streaming && !content ? (
        <StatusIndicator tone="info" pulse>
          Thinking
        </StatusIndicator>
      ) : null}
      {content ? (
        <MessageMarkdown content={content} isStreaming={streaming} />
      ) : null}
    </div>
  );
};

export default TextPart;
