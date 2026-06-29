import React, { useState } from "react";
import { ChevronRight, Lightbulb } from "lucide-react";
import { Streamdown } from "streamdown";
import { cn } from "@/lib/utils";
import { useFormatTimestamp } from "../../../utils/dateUtils";
import { LLMResponseData } from "../types";
import { fileAwareMarkdownComponents, preprocessFileLinks } from "../utils/markdownComponents";
import MessageWrapper from "./MessageWrapper";

const ThinkingBlock: React.FC<{ content: string }> = ({ content }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="mb-2 rounded-lg border border-sky-100 bg-sky-50/40 dark:border-sky-900/60 dark:bg-sky-950/20">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-xs text-sky-600 dark:text-sky-300"
      >
        <ChevronRight
          className={cn("h-3 w-3 transition-transform", isExpanded && "rotate-90")}
        />
        <Lightbulb className="h-3 w-3" />
        <span className="font-medium">Reasoning</span>
      </button>
      {isExpanded && (
        <div className="whitespace-pre-wrap px-3 pb-2 text-xs text-sky-700/90 dark:text-sky-200/80">
          {content}
        </div>
      )}
    </div>
  );
};

export const LLMResponseMessage: React.FC<{
  data: LLMResponseData;
  agent_name?: string;
}> = ({ data, agent_name }) => {
  const formatTimestamp = useFormatTimestamp();
  return (
    <MessageWrapper>
      <div className="min-w-0 flex-1 pb-1">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-medium text-foreground">
            {agent_name || "Assistant"}
          </span>
          <span className="text-muted-foreground">
            {formatTimestamp(data.timestamp)}
          </span>
        </div>

        {data.thinking && <ThinkingBlock content={data.thinking} />}

        <Streamdown
          className="prose prose-sm mt-1 max-w-none text-zinc-700 dark:prose-invert dark:text-zinc-300"
          components={fileAwareMarkdownComponents as any}
          linkSafety={{ enabled: false }}
        >
          {preprocessFileLinks(data.content)}
        </Streamdown>
      </div>
    </MessageWrapper>
  );
};

export default LLMResponseMessage;
