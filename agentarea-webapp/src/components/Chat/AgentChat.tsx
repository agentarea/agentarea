"use client";

import React from "react";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { AssistantMessage as AssistantMessageComponent } from "./componets/AssistantMessage";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import { MessageRenderer } from "./MessageComponents";
import { ChatInputArea } from "./componets/ChatInputArea";
import { parseSSEStream } from "./handlers/sseParser";
import { createSSEEventHandler } from "./handlers/eventHandlers";

// Import hooks
import { useScrollManagement } from "./hooks/useScrollManagement";
import { useFileUpload } from "./hooks/useFileUpload";
import { useTaskLifecycle } from "./hooks/useTaskLifecycle";
import { useChatMessages, type ChatMessage, type UserChatMessage } from "./hooks/useChatMessages";

interface AgentChatProps {
  agent: {
    id: string;
    name: string;
    description?: string | null;
  };
  taskId?: string;
  initialMessages?: ChatMessage[];
  onTaskCreated?: (taskId: string) => void;
  className?: string;
  height?: string;
}

export default function AgentChat({
  agent,
  taskId,
  initialMessages = [],
  onTaskCreated,
  className = "",
  height = "600px",
}: AgentChatProps) {
  // Hooks for state management
  const { messages, setMessages, addUserMessage } = useChatMessages({
    agentName: agent.name,
    agentId: agent.id,
    initialMessages,
  });

  const {
    currentTaskId,
    setCurrentTaskId,
    callbacks,
  } = useTaskLifecycle(agent.id, {
    initialTaskId: taskId,
    onTaskCreated,
  });

  const {
    messagesContainerRef,
    messagesEndRef,
    isAtBottom,
    handleScroll,
    scrollToBottom,
    checkIfAtBottom,
  } = useScrollManagement({
    messagesCount: messages.length,
  });

  const {
    selectedFiles,
    fileInputRef,
    handleFileSelect,
    removeFile,
    openFileDialog,
    clearFiles,
  } = useFileUpload();

  // State for loading and input
  const [isLoading, setIsLoading] = React.useState(false);
  const [input, setInput] = React.useState("");
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  // Handle input change with auto-resize
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    adjustTextareaHeight();
  };

  // Auto-resize textarea function
  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const scrollHeight = textarea.scrollHeight;
      const maxHeight = 3 * 24; // 3 lines * 24px line height
      textarea.style.height = `${Math.min(scrollHeight, maxHeight)}px`;
    }
  };

  // SSE message handler
  const handleSSEMessage = React.useCallback(
    createSSEEventHandler({
      currentTaskId,
      setMessages,
      setIsLoading,
      setCurrentTaskId,
      onTaskCreated: callbacks.onTaskCreated.current,
    }),
    [currentTaskId, callbacks]
  );

  // Send message handler
  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if ((!input.trim() && selectedFiles.length === 0) || isLoading) return;

    const userMessage: UserChatMessage = {
      id: Date.now().toString(),
      content: input,
      role: "user",
      timestamp: new Date().toISOString(),
      files: selectedFiles.length > 0 ? selectedFiles : undefined,
    };

    addUserMessage(userMessage);
    setInput("");
    clearFiles();
    setIsLoading(true);

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    try {
      // Create task with SSE streaming through Next.js API route (handles auth)
      const response = await fetch(`/api/agents/${agent.id}/tasks/create`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          description: userMessage.content,
          parameters: {
            context: {},
            task_type: "chat",
            session_id: `chat-${Date.now()}`,
          },
          enable_agent_communication: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      if (!response.body) {
        throw new Error("No response body");
      }

      const reader = response.body.getReader();

      await parseSSEStream(reader, {
        onEvent: handleSSEMessage,
        buffered: false, // AgentChat uses unbuffered parsing
      });
    } catch (error) {
      console.error("Failed to send message:", error);
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, I couldn't process your message. Error: ${error}`,
        role: "assistant",
        timestamp: new Date().toISOString(),
        agent_id: agent.id,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Card
      className={cn(
        "flex h-full max-h-full cursor-auto flex-col justify-between overflow-hidden p-0 shadow-none hover:shadow-none",
        className
      )}
    >
      <CardHeader className="border-b p-4">
        <CardTitle className="flex items-center gap-2">
          Chat with {agent.name}
        </CardTitle>
      </CardHeader>

      <CardContent className="relative flex flex-1 flex-col overflow-auto bg-chatBackground p-0">
        {/* Messages */}
        <div
          ref={messagesContainerRef}
          onScroll={handleScroll}
          className="flex-1 space-y-3 overflow-y-auto px-3 py-3"
        >
          {messages.map((message, index) => {
            // Handle different message types
            if ("type" in message) {
              // This is a MessageComponentType - use MessageRenderer
              return (
                <MessageRenderer
                  key={`${message.data.id}-${message.data.event_type}-${index}`}
                  message={message}
                  agent_name={agent.name}
                />
              );
            } else if (message.role === "user") {
              // User message
              return (
                <UserMessageComponent
                  key={message.id}
                  id={message.id}
                  content={message.content}
                  timestamp={message.timestamp}
                  files={message.files}
                />
              );
            } else {
              // Assistant welcome message
              return (
                <AssistantMessageComponent
                  key={message.id}
                  id={message.id}
                  content={message.content}
                  timestamp={message.timestamp}
                  agent_id={message.agent_id}
                  agent_name={agent.name}
                />
              );
            }
          })}
          <div ref={messagesEndRef} className="aa-messages-end" />
        </div>

        {/* Scroll to bottom button */}
        <div
          className={`absolute bottom-4 right-4 z-20 transition-opacity duration-200 ${isAtBottom ? "pointer-events-none opacity-0" : "opacity-100"}`}
        >
          <Button
            onClick={() => {
              scrollToBottom();
              requestAnimationFrame(() => {
                const atBottom = checkIfAtBottom();
                // isAtBottom state is managed by scroll handler
              });
            }}
            size="sm"
            className="h-8 w-8 rounded-full bg-white text-text shadow-lg hover:text-white dark:bg-zinc-900 dark:text-zinc-200"
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>

      <CardFooter className="p-0">
        {/* Input */}
        <div className="w-full border-t p-4">
          <ChatInputArea
            input={input}
            onInputChange={handleInputChange}
            onSubmit={sendMessage}
            isLoading={isLoading}
            placeholder={`Message ${agent.name}...`}
            selectedFiles={selectedFiles}
            onRemoveFile={removeFile}
            onOpenFileDialog={openFileDialog}
            fileInputRef={fileInputRef}
            textareaRef={textareaRef}
            variant="default"
            sendButtonIcon="send"
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage(e);
              }
            }}
          />
        </div>
      </CardFooter>
    </Card>
  );
}
