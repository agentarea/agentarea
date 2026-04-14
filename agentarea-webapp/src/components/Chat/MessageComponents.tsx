import React from "react";
import A2UIMessage from "./componets/A2UIMessage";
import ApprovalRequestMessage from "./componets/ApprovalRequestMessage";
import ErrorMessage from "./componets/ErrorMessage";
import LLMChunkMessage from "./componets/LLMChunkMessage";
import LLMResponseMessage from "./componets/LLMResponseMessage";
import SystemMessage from "./componets/SystemMessage";
import ToolCallGroupMessage from "./componets/ToolCallGroupMessage";
import ToolCallStartedMessage from "./componets/ToolCallStartedMessage";
import ToolResultMessage from "./componets/ToolResultMessage";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import WorkflowResultMessage from "./componets/WorkflowResultMessage";
import { A2UIAction, MessageComponentType } from "./types";

// Export the type for use in other components
export type { MessageComponentType };

// Message renderer that picks the right component
export const MessageRenderer: React.FC<{
  message: MessageComponentType;
  agent_name?: string;
  onA2UIAction?: (
    action: A2UIAction,
    surfaceId: string,
    sourceComponentId: string,
  ) => void;
  onResolveEscalation?: (escalationId: string, approved: boolean, comment: string) => void;
}> = ({ message, agent_name, onA2UIAction, onResolveEscalation }) => {
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
    case "tool_call_group":
      return <ToolCallGroupMessage data={message.data} key={message.data.id} />;
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
    case "a2ui_surface":
      return (
        <A2UIMessage
          data={message.data}
          key={message.data.id}
          onAction={
            onA2UIAction
              ? (action, sourceId) =>
                  onA2UIAction(action, message.data.surfaceId, sourceId)
              : undefined
          }
        />
      );
    case "approval_request":
      return (
        <ApprovalRequestMessage
          data={{...message.data, _onResolve: onResolveEscalation}}
          key={message.data.id}
        />
      );
    case "user_message":
      return (
        <UserMessageComponent
          id={message.data.id}
          content={message.data.content}
          timestamp={message.data.timestamp}
          key={message.data.id}
        />
      );
    default:
      return null;
  }
};
