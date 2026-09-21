import React, { useState } from "react";
import { ChevronRight, Lightbulb } from "lucide-react";
import { MessageMarkdown } from "@/components/Chat/MessageMarkdown";
import { cn } from "@/lib/utils";
import { useFormatTimestamp } from "../../../utils/dateUtils";
import { LLMResponseData } from "../types";
import MessageWrapper from "./MessageWrapper";

const ThinkingBlock: React.FC<{ content: string }> = ({ content }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="my-2">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
        className="flex w-full items-center gap-1.5 rounded-md py-1 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 transition-transform",
            isExpanded && "rotate-90"
          )}
        />
        <Lightbulb className="h-3 w-3" />
        <span className="font-medium">Reasoning</span>
      </button>
      {isExpanded && (
        <div className="whitespace-pre-wrap py-2 pl-5 text-xs leading-5 text-muted-foreground">
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
        <div className="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
          <span>{agent_name || "Assistant"}</span>
          <span className="text-muted-foreground">
            {formatTimestamp(data.timestamp)}
          </span>
        </div>

        {data.thinking && <ThinkingBlock content={data.thinking} />}

        <MessageMarkdown className="mt-1" content={data.content} />
      </div>
    </MessageWrapper>
  );
};

export default LLMResponseMessage;
