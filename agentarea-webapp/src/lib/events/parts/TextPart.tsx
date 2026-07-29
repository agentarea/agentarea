import React from "react";
import type { Part } from "../contract";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { stripA2UIFromStreamingContent } from "../a2ui";

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
  const streaming = part.eventType === "llm.call.chunk";
  const failed = part.eventType === "llm.call.failed";

  return (
    <div className="flex flex-col gap-1">
      {failed ? (
        <StatusIndicator tone="danger">LLM call failed</StatusIndicator>
      ) : streaming ? (
        <StatusIndicator tone="info" pulse>
          Thinking
        </StatusIndicator>
      ) : null}
      {content ? (
        <p className="whitespace-pre-wrap text-sm text-foreground">{content}</p>
      ) : null}
    </div>
  );
};

export default TextPart;
