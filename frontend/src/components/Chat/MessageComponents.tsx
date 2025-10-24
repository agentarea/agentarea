import React from "react";
import ErrorMessage from "./componets/ErrorMessage";
import LLMChunkMessage from "./componets/LLMChunkMessage";
import LLMResponseMessage from "./componets/LLMResponseMessage";
import SystemMessage from "./componets/SystemMessage";
import ToolCallStartedMessage from "./componets/ToolCallStartedMessage";
import ToolResultMessage from "./componets/ToolResultMessage";
import WorkflowResultMessage from "./componets/WorkflowResultMessage";
import { MessageComponentType } from "./types";

// Export the type for use in other components
export type { MessageComponentType };

// Message renderer that picks the right component
export const MessageRenderer: React.FC<{
  message: MessageComponentType;
  agent_name?: string;
}> = ({ message, agent_name }) => {
  switch (message.type) {
    case "llm_response":
      return (
        <LLMResponseMessage
          data={message.data}
          key={message.data.id}
          agent_name={agent_name}
        />
      );
    case "llm_chunk":
      return (
        <LLMChunkMessage
          data={message.data}
          key={message.data.id}
          agent_name={agent_name}
        />
      );
    case "tool_call_started":
      return (
        <ToolCallStartedMessage data={message.data} key={message.data.id} />
      );
    case "tool_result":
      return <ToolResultMessage data={message.data} key={message.data.id} />;
    case "error":
      return <ErrorMessage data={message.data} key={message.data.id} />;
    case "workflow_result":
      return (
        <WorkflowResultMessage
          data={message.data}
          key={message.data.id}
          agent_name={agent_name}
        />
      );
    case "system":
      return <SystemMessage data={message.data} key={message.data.id} />;
    default:
      return null;
  }
};
