"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { ChevronDown } from "lucide-react";
import { toast } from "sonner";
import type { HumanInputSecretValue } from "@/components/Chat/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useTaskActions } from "@/hooks/useTaskActions";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import { useTaskEvents } from "@/lib/events/useTaskEvents";
import { cn } from "@/lib/utils";
import ActivityGroup from "./ActivityGroup";
import { buildActivitySegments } from "./activityView";
import { ChatInputArea } from "./componets/ChatInputArea";
import { useFileUpload } from "./hooks/useFileUpload";
import { useScrollManagement } from "./hooks/useScrollManagement";
import { deliverTaskMessage } from "./utils/deliverTaskMessage";

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

  const {
    parts,
    pendingForm,
    terminalMessage,
    status: streamStatus,
    completedRuns,
  } = useTaskEvents(agent.id, taskId, {
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

  const {
    selectedFiles,
    fileInputRef,
    handleFileSelect,
    removeFile,
    openFileDialog,
    clearFiles,
  } = useFileUpload();

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
      secrets: Record<string, HumanInputSecretValue>
    ) => {
      const { error } = await actions.submitInput(
        inputRequestId,
        answers,
        secrets
      );
      if (error) toast.error("Failed to submit response");
    },
    [actions]
  );

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const message = input.trim();
    if ((!message && selectedFiles.length === 0) || sending) return;
    setSending(true);
    try {
      const delivery = await deliverTaskMessage({
        actions,
        files: selectedFiles,
        message,
        pendingInputId:
          pendingForm?.eventType === "input.request"
            ? pendingForm.partId
            : undefined,
        queueOnCurrentTask: QUEUEABLE_STATUSES.includes(status),
      });
      if (delivery.route === "followup" && !delivery.taskId) {
        toast.error("Failed to create new task");
        return;
      }
      if (delivery.route === "input" && delivery.error) {
        toast.error("Failed to submit response");
        return;
      }
      if (delivery.route === "queue" && delivery.error) {
        toast.error("Failed to send message");
        return;
      }

      setInput("");
      clearFiles();
      if (textareaRef.current) textareaRef.current.style.height = "auto";
      if (delivery.route === "followup" && delivery.taskId) {
        router.push(`/tasks/${delivery.taskId}`);
      }
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
        className
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
          className="mx-auto flex w-full max-w-3xl flex-1 flex-col space-y-4 overflow-y-auto px-4 py-4 md:px-6"
        >
          {buildActivitySegments(parts, completedRuns).map((segment) =>
            segment.kind === "work" ? (
              <ActivityGroup
                key={segment.run.id}
                run={segment.run}
                onFormSubmit={handleFormSubmit}
              />
            ) : (
              <PartRenderer
                key={segment.part.partId}
                part={segment.part}
                onFormSubmit={handleFormSubmit}
              />
            )
          )}
          {terminalMessage && streamStatus !== "completed" && (
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
        <div className="w-full bg-background">
          <div className="mx-auto w-full max-w-3xl px-4 py-3 md:px-6">
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
              onFileSelect={handleFileSelect}
              attachmentNotice={`Files will be sent in a new task with ${agent.name}.`}
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
        </div>
      </CardFooter>
    </Card>
  );
}
