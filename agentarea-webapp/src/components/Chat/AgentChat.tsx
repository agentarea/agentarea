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
import { useTaskConversation } from "@/hooks/useTaskConversation";
import { MessageRenderer } from "./MessageComponents";
import { ChatInputArea } from "./componets/ChatInputArea";
import { useScrollManagement } from "./hooks/useScrollManagement";
import { useFileUpload } from "./hooks/useFileUpload";
import { useA2UIActions } from "./hooks/useA2UIActions";

interface AgentChatProps {
  agent: {
    id: string;
    name: string;
    description?: string | null;
  };
  taskId: string;
  /** Live task status; drives send routing (answer input / queue / new task). */
  status?: string;
  className?: string;
  height?: string;
}

export default function AgentChat({
  agent,
  taskId,
  status,
  className = "",
}: AgentChatProps) {
  const { messages, isActive, actions } = useTaskConversation(
    agent.id,
    taskId,
    { status },
  );

  const { dispatchAction: dispatchA2UIAction } = useA2UIActions(
    agent.id,
    taskId,
  );

  const {
    messagesContainerRef,
    messagesEndRef,
    isAtBottom,
    handleScroll,
    scrollToBottom,
    checkIfAtBottom,
  } = useScrollManagement({ messagesCount: messages.length });

  const { selectedFiles, fileInputRef, removeFile, openFileDialog } =
    useFileUpload();

  const [input, setInput] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 3 * 24)}px`;
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const message = input.trim();
    if (!message || sending) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setSending(true);
    try {
      await actions.sendMessage(message);
    } finally {
      setSending(false);
    }
  };

  return (
    <Card
      className={cn(
        "flex h-full max-h-full cursor-auto flex-col justify-between overflow-hidden p-0 shadow-none hover:shadow-none",
        className,
      )}
    >
      <CardHeader className="border-b p-4">
        <CardTitle className="flex items-center gap-2">
          Chat with {agent.name}
        </CardTitle>
      </CardHeader>

      <CardContent className="relative flex flex-1 flex-col overflow-auto bg-chatBackground p-0">
        <div
          ref={messagesContainerRef}
          onScroll={handleScroll}
          className="flex-1 space-y-3 overflow-y-auto px-3 py-3"
        >
          {messages.map((message, index) => (
            <MessageRenderer
              key={`${message.data.id}-${message.data.event_type}-${index}`}
              message={message}
              agent_name={agent.name}
              onA2UIAction={dispatchA2UIAction}
              onResolveEscalation={actions.resolveEscalation}
              onSubmitInput={actions.submitInput}
            />
          ))}
          <div ref={messagesEndRef} className="aa-messages-end" />
        </div>

        <div
          className={`absolute bottom-4 right-4 z-20 transition-opacity duration-200 ${isAtBottom ? "pointer-events-none opacity-0" : "opacity-100"}`}
        >
          <Button
            onClick={() => {
              scrollToBottom();
              requestAnimationFrame(() => {
                checkIfAtBottom();
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
        <div className="w-full border-t p-4">
          <ChatInputArea
            input={input}
            onInputChange={handleInputChange}
            onSubmit={handleSend}
            isLoading={sending}
            placeholder={
              isActive
                ? `Message ${agent.name}...`
                : `Send a follow-up to ${agent.name}...`
            }
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
                handleSend(e);
              }
            }}
          />
        </div>
      </CardFooter>
    </Card>
  );
}
