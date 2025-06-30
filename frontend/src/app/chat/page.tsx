"use client";

import { CopilotChat } from "@copilotkit/react-ui";
import { useCopilotAction } from "@copilotkit/react-core";

export default function ChatPage() {
  // Example action for agent communication
  useCopilotAction({
    name: "execute_agent_task",
    description: "Execute a task using AgentArea agents",
    parameters: [
      {
        name: "task_description",
        type: "string",
        description: "Description of the task to execute",
        required: true,
      },
      {
        name: "agent_id",
        type: "string", 
        description: "ID of the agent to use (optional)",
        required: false,
      }
    ],
    handler: async ({ task_description, agent_id }) => {
      // This will be handled by our AG-UI backend
      return `Task "${task_description}" submitted${agent_id ? ` to agent ${agent_id}` : ''}.`;
    },
  });

  return (
    <div className="flex flex-col h-screen bg-background">
      <div className="border-b border-border px-6 py-4">
        <h1 className="text-2xl font-semibold text-foreground">
          AgentArea Chat
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Chat with your AI agents using A2A protocol via AG-UI
        </p>
      </div>
      
      <div className="flex-1 p-6">
        <CopilotChat
          className="h-full max-w-4xl mx-auto"
          labels={{
            title: "AgentArea Assistant",
            initial: "Hello! I'm your AgentArea assistant. I can help you execute tasks using your configured agents. What would you like me to help you with?",
          }}
          instructions="You are an AI assistant that helps users interact with AgentArea agents. You can execute tasks, answer questions about the platform, and help users navigate their agent workflows. When users ask you to perform tasks, use the execute_agent_task action."
        />
      </div>
    </div>
  );
} 