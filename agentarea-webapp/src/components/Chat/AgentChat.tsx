"use client";

import React from "react";
import { ChevronDown } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { cn } from "@/lib/utils";
import { useTaskEvents } from "@/lib/events/useTaskEvents";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import { useTaskActions } from "@/hooks/useTaskActions";
import type { HumanInputSecretValue } from "@/components/Chat/types";
import { ChatInputArea } from "./componets/ChatInputArea";
import { useScrollManagement } from "./hooks/useScrollManagement";
import { useFileUpload } from "./hooks/useFileUpload";

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

// Statuses where the workflow is still alive and a free-text message should be
// queued for the next iteration rather than starting a new task.
const QUEUEABLE_STATUSES = ["running", "paused", "blocked", "completed"];

export default function AgentChat({
  agent,
  taskId,
  status = "",
  className = "",
}: AgentChatProps) {
  const router = useRouter();

  const { parts, pendingForm, terminalMessage, status: streamStatus } =
    useTaskEvents(agent.id, taskId, {
      includeHistory: true,
      autoConnect: true,
    });

  const actions = useTaskActions(agent.id, taskId);

  const {
    messagesContainerRef,
    messagesEndRef,
    isAtBottom,
    handleScroll,
    scrollToBottom,
    checkIfAtBottom,
  } = useScrollManagement({ messagesCount: parts.length });

  const { selectedFiles, fileInputRef, removeFile, openFileDialog } =
    useFileUpload();

  const [input, setInput] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const isActive =
    QUEUEABLE_STATUSES.includes(status) || status === "waiting_for_input";

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 3 * 24)}px`;
    }
  };

  const handleFormSubmit = React.useCallback(
    async (
      inputRequestId: string,
      answers: Record<string, unknown>,
      secrets: Record<string, HumanInputSecretValue>,
    ) => {
      const { error } = await actions.submitInput(
        inputRequestId,
        answers,
        secrets,
      );
      if (error) toast.error("Failed to submit response");
    },
    [actions],
  );

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const message = input.trim();
    if (!message || sending) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setSending(true);
    try {
      if (pendingForm && pendingForm.eventType === "input.request") {
        const { error } = await actions.submitInput(
          pendingForm.partId,
          { answer: message },
          {},
        );
        if (error) toast.error("Failed to submit response");
        return;
      }

      if (QUEUEABLE_STATUSES.includes(status)) {
        const { error } = await actions.queueMessage(message);
        if (error) toast.error("Failed to send message");
        return;
      }

      const newTaskId = await actions.createFollowupTask(message);
      if (newTaskId) router.push(`/tasks/${newTaskId}`);
      else toast.error("Failed to create new task");
    } catch (err) {
      toast.error("Failed to send message", {
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSending(false);
    }
  };

  const terminalTone =
    streamStatus === "failed"
      ? "danger"
      : streamStatus === "cancelled"
        ? "warning"
        : "success";

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
          {parts.map((part) => (
            <PartRenderer
              key={part.partId}
              part={part}
              onFormSubmit={handleFormSubmit}
            />
          ))}
          {terminalMessage && (
            <StatusIndicator tone={terminalTone}>
              {terminalMessage}
            </StatusIndicator>
          )}
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
            <ChevronDown />
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
