import React, { useState } from "react";
import { ChevronRight, Lightbulb } from "lucide-react";
import { Streamdown } from "streamdown";
import { cn } from "@/lib/utils";
import { stripA2UIFromStreamingContent } from "../utils/messageAccumulator";
import { fileAwareMarkdownComponents, preprocessFileLinks } from "../utils/markdownComponents";
import MessageWrapper from "./MessageWrapper";

interface LLMChunkData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
  chunk_type?: "text" | "thinking";
  thinking?: string;
}

const ThinkingBlock: React.FC<{ content: string; isStreaming?: boolean }> = ({
  content,
  isStreaming,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <div className="mb-2 rounded-lg border border-violet-100 bg-violet-50/40 dark:border-violet-900/60 dark:bg-violet-950/20">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-xs text-violet-600 dark:text-violet-300"
      >
        <ChevronRight
          className={cn("h-3 w-3 transition-transform", isExpanded && "rotate-90")}
        />
        <Lightbulb className="h-3 w-3" />
        <span className="font-medium">{isStreaming ? "Reasoning…" : "Reasoning"}</span>
      </button>
      {isExpanded && (
        <div className="whitespace-pre-wrap px-3 pb-2 text-xs text-violet-700/90 dark:text-violet-200/80">
          {content}
        </div>
      )}
    </div>
  );
};

const LLMChunkMessage: React.FC<{
  data: LLMChunkData;
  agent_name?: string;
}> = ({ data, agent_name }) => {
  const isThinkingOnly = data.chunk_type === "thinking" && !data.chunk;
  const hasThinking = !!data.thinking;
  const status = data.is_final
    ? null
    : isThinkingOnly
      ? "Thinking…"
      : "Responding…";

  return (
    <MessageWrapper>
      <div className="min-w-0 flex-1 pb-1">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-medium text-foreground">
            {agent_name || "Assistant"}
          </span>
          {status && (
            <span className="animate-pulse text-muted-foreground">{status}</span>
          )}
        </div>

        {hasThinking && (
          <ThinkingBlock
            content={data.thinking!}
            isStreaming={!data.chunk && !data.is_final}
          />
        )}

        {data.chunk && (
          <Streamdown
            parseIncompleteMarkdown
            className="prose prose-sm mt-1 max-w-none text-zinc-700 dark:prose-invert dark:text-zinc-300"
            components={fileAwareMarkdownComponents as any}
            linkSafety={{ enabled: false }}
          >
            {preprocessFileLinks(stripA2UIFromStreamingContent(data.chunk))}
          </Streamdown>
        )}
      </div>
    </MessageWrapper>
  );
};

export default LLMChunkMessage;
