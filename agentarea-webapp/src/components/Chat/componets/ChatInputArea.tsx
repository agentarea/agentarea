/**
 * Shared chat input area component
 * Supports text input, file attachments, and mentions
 */

import React from "react";
import { useTranslations } from "next-intl";
import {
  ArrowUp,
  FolderKanban,
  Paperclip,
  Pause,
  Play,
  Send,
  ShieldCheck,
} from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { AttachmentCard } from "@/components/ui/attachment-card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getAgentIconComponent, resolveAgentIdentity } from "@/lib/agent-identity";
import { cn } from "@/lib/utils";
import { ContextSelect } from "./ContextSelect";
import { MentionMenu } from "../MentionMenu";

const NO_PROJECT_VALUE = "__no_project__";
const DEFAULT_TASK_POLICY_VALUE = "__default_task_policy__";

export interface MentionMenuProps {
  show: boolean;
  agents: Array<{ id: string; name: string; description?: string | null }>;
  position: {
    top: number;
    left: number;
    width: number;
    side: "top" | "bottom";
  };
  selectedIndex: number;
  menuRef:
    | React.RefObject<HTMLDivElement>
    | React.RefObject<HTMLDivElement | null>;
  onAgentSelect: (agent: { id: string; name: string }) => void;
}

export interface ChatInputAreaProps {
  /**
   * Input value (with mention IDs)
   */
  input: string;

  /**
   * Display value (formatted for textarea)
   */
  inputDisplay?: string;

  /**
   * Input change handler
   */
  onInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;

  /**
   * Form submit handler
   */
  onSubmit: (e: React.FormEvent) => void;

  /**
   * Loading state
   */
  isLoading: boolean;

  /**
   * Placeholder text
   */
  placeholder: string;

  /**
   * Selected files
   */
  selectedFiles: File[];

  /**
   * Remove file handler
   */
  onRemoveFile: (index: number) => void;

  /**
   * Open file dialog handler
   */
  onOpenFileDialog: () => void;

  /**
   * File input ref
   */
  fileInputRef:
    | React.RefObject<HTMLInputElement>
    | React.RefObject<HTMLInputElement | null>;

  /**
   * Textarea ref
   */
  textareaRef:
    | React.RefObject<HTMLTextAreaElement>
    | React.RefObject<HTMLTextAreaElement | null>;

  /**
   * Keydown handler (for mentions, submit)
   */
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;

  /**
   * Mention menu props (optional)
   */
  mentionProps?: MentionMenuProps;

  /**
   * Container ref (for mention menu positioning)
   */
  containerRef?:
    | React.RefObject<HTMLDivElement>
    | React.RefObject<HTMLDivElement | null>;

  /**
   * Variant style
   */
  variant?: "default" | "centered";

  /**
   * Show send button (default true)
   */
  showSendButton?: boolean;

  /**
   * Send button icon variant
   */
  sendButtonIcon?: "arrow" | "send";

  /**
   * Number of rows for textarea
   */
  rows?: number;

  /**
   * Additional className for form
   */
  className?: string;

  /**
   * Additional className for container
   */
  containerClassName?: string;

  /**
   * Current agent (for agent selector)
   */
  currentAgent?: {
    id: string;
    name: string;
    description?: string | null;
    icon?: string | null;
    color_token?: string | null;
  };

  /**
   * Available agents (for agent selector)
   */
  availableAgents?: Array<{
    id: string;
    name: string;
    description?: string | null;
    icon?: string | null;
    color_token?: string | null;
  }>;

  /**
   * Agent change handler
   */
  onAgentChange?: (agent: {
    id: string;
    name: string;
    description?: string | null;
    icon?: string | null;
    color_token?: string | null;
  }) => void;

  /**
   * Current project id
   */
  currentProjectId?: string | null;

  /**
   * Available projects
   */
  availableProjects?: Array<{
    id: string;
    name: string;
    description?: string | null;
  }>;

  /**
   * Project change handler
   */
  onProjectChange?: (projectId: string | null) => void;

  /**
   * Current task policy id
   */
  currentTaskPolicyId?: string | null;

  /**
   * Available task policies
   */
  availableTaskPolicies?: Array<{
    id: string;
    name: string;
    description?: string | null;
  }>;

  /**
   * Task policy change handler
   */
  onTaskPolicyChange?: (policyId: string | null) => void;

  /**
   * Stop/Pause handler
   */
  onStop?: () => void;

  /**
   * Continue/Resume handler
   */
  onResume?: () => void;

  /**
   * Is stopping state
   */
  isStopping?: boolean;

  /**
   * Is resuming state
   */
  isResuming?: boolean;

  /**
   * Render resume button instead of stop
   */
  canResume?: boolean;
}

/**
 * Shared chat input area component
 *
 * Features:
 * - Text input with auto-resize
 * - File attachments with preview
 * - Mention support (optional)
 * - Loading state
 * - Keyboard shortcuts (Enter to send, Shift+Enter for newline)
 * - Multiple styling variants
 *
 * @example
 * ```typescript
 * <ChatInputArea
 *   input={input}
 *   onInputChange={handleInputChange}
 *   onSubmit={sendMessage}
 *   isLoading={isLoading}
 *   placeholder="Type a message..."
 *   selectedFiles={selectedFiles}
 *   onRemoveFile={removeFile}
 *   onOpenFileDialog={openFileDialog}
 *   fileInputRef={fileInputRef}
 *   textareaRef={textareaRef}
 *   variant="centered"
 * />
 * ```
 */
export function ChatInputArea({
  input,
  inputDisplay,
  onInputChange,
  onSubmit,
  isLoading,
  placeholder,
  selectedFiles,
  onRemoveFile,
  onOpenFileDialog,
  fileInputRef,
  textareaRef,
  onKeyDown,
  mentionProps,
  containerRef,
  variant = "default",
  showSendButton = true,
  sendButtonIcon = "arrow",
  rows = 3,
  className,
  containerClassName,
  currentAgent,
  availableAgents,
  onAgentChange,
  currentProjectId,
  availableProjects,
  onProjectChange,
  currentTaskPolicyId,
  availableTaskPolicies,
  onTaskPolicyChange,
  onStop,
  onResume,
  isStopping = false,
  isResuming = false,
  canResume = false,
}: ChatInputAreaProps) {
  const t = useTranslations("Chat.inputControls");
  const SendIcon = sendButtonIcon === "arrow" ? ArrowUp : Send;
  const showContextControls =
    Boolean(currentAgent && availableAgents?.length && onAgentChange) ||
    Boolean(availableProjects?.length && onProjectChange) ||
    Boolean(availableTaskPolicies?.length && onTaskPolicyChange);

  return (
    <div
      ref={containerRef}
      className={cn(
        "w-full",
        // variant === "centered" && "mx-auto max-w-3xl",
        containerClassName
      )}
    >
      <form
        onSubmit={onSubmit}
        className={cn(
          "relative flex flex-col gap-2 transition-all duration-700 ease-out",
          className
        )}
      >
        <Textarea
          ref={textareaRef}
          value={inputDisplay || input}
          onChange={onInputChange}
          placeholder={placeholder}
          disabled={isLoading}
          className={cn(
            "resize-none transition-all duration-700 ease-out",
            variant === "centered"
              ? "min-h-auto h-auto border-none pb-0 pr-12 pt-3"
              : "max-h-[72px] min-h-[40px] rounded-3xl border py-2 pr-12 transition-colors duration-200 focus:border-primary/50"
          )}
          rows={rows}
          onKeyDown={onKeyDown}
        />

        <div className="flex flex-col gap-2">
          {/* Selected Files Display */}
          <div className="flex flex-row flex-wrap gap-2">
            {selectedFiles.length > 0 &&
              selectedFiles.map((file, index) => (
                <AttachmentCard
                  key={index}
                  file={file}
                  onAction={() => onRemoveFile(index)}
                  actionType="remove"
                />
              ))}
          </div>

          <div className="flex flex-wrap items-end gap-2 sm:flex-nowrap">
            {showContextControls ? (
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 overflow-hidden sm:flex-nowrap sm:gap-2">
                {currentAgent && availableAgents?.length && onAgentChange ? (
                  <div className="basis-full sm:basis-auto">
                    <ContextSelect
                      className="min-w-0 sm:shrink"
                      icon={FolderKanban}
                      label={t("agent")}
                      value={currentAgent.id}
                      disabled={isLoading}
                      onValueChange={(agentId) => {
                        const nextAgent = availableAgents.find(
                          (agent) => agent.id === agentId
                        );
                        if (nextAgent) onAgentChange(nextAgent);
                      }}
                      options={availableAgents}
                      renderTriggerIcon={(option) => {
                        const { iconKey } = resolveAgentIdentity(option);
                        const Icon = getAgentIconComponent(iconKey);

                        return (
                          <Icon
                            className="h-3.5 w-3.5 shrink-0 text-zinc-400 dark:text-zinc-300"
                            strokeWidth={2}
                          />
                        );
                      }}
                      renderOptionIcon={(option) => (
                        <AgentAvatar
                          agent={option}
                          size="xs"
                          className="mt-0.5 shrink-0"
                        />
                      )}
                    />
                  </div>
                ) : null}

                {availableProjects?.length && onProjectChange ? (
                  <ContextSelect
                    className="shrink min-w-0"
                    icon={FolderKanban}
                    label={t("project")}
                    value={currentProjectId ?? NO_PROJECT_VALUE}
                    disabled={isLoading}
                    onValueChange={(projectId) =>
                      onProjectChange(
                        projectId === NO_PROJECT_VALUE ? null : projectId
                      )
                    }
                    options={[
                      { id: NO_PROJECT_VALUE, name: t("noProject") },
                      ...availableProjects,
                    ]}
                  />
                ) : null}

                {availableTaskPolicies?.length && onTaskPolicyChange ? (
                  <ContextSelect
                    className="shrink min-w-0"
                    icon={ShieldCheck}
                    label={t("taskPolicy")}
                    value={currentTaskPolicyId ?? DEFAULT_TASK_POLICY_VALUE}
                    disabled={isLoading}
                    onValueChange={(policyId) =>
                      onTaskPolicyChange(
                        policyId === DEFAULT_TASK_POLICY_VALUE ? null : policyId
                      )
                    }
                    options={[
                      {
                        id: DEFAULT_TASK_POLICY_VALUE,
                        name: t("defaultPolicy"),
                      },
                      ...availableTaskPolicies,
                    ]}
                  />
                ) : null}
              </div>
            ) : (
              <div className="flex-1" />
            )}

            {/* Action Buttons */}
            <div className="ml-auto flex shrink-0 items-center justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onOpenFileDialog}
                disabled={isLoading}
                className="h-8 w-8 rounded-full p-0 hover:bg-zinc-200 hover:text-text dark:hover:bg-gray-800"
              >
                <Paperclip className="h-4 w-4" />
              </Button>

              {showSendButton && (
                <>
                  {canResume && onResume ? (
                    <Button
                      type="button"
                      size="icon"
                      variant="outline"
                      onClick={onResume}
                      disabled={isResuming}
                      className="h-8 w-8 rounded-full shadow-sm transition-all duration-200 hover:shadow-md"
                    >
                      {isResuming ? (
                        <LoadingSpinner size="sm" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                    </Button>
                  ) : isLoading && onStop ? (
                    <Button
                      type="button"
                      size="icon"
                      variant="destructive"
                      onClick={onStop}
                      disabled={isStopping}
                      className="h-8 w-8 rounded-full shadow-sm transition-all duration-200 hover:shadow-md"
                    >
                      {isStopping ? (
                        <LoadingSpinner variant="light" size="sm" />
                      ) : (
                        <Pause className="h-4 w-4" />
                      )}
                    </Button>
                  ) : (
                    <Button
                      type="submit"
                      size="icon"
                      disabled={
                        isLoading ||
                        (!input.trim() && selectedFiles.length === 0)
                      }
                      className="h-8 w-8 rounded-full shadow-sm transition-all duration-200 hover:shadow-md"
                    >
                      {isLoading ? (
                        <LoadingSpinner variant="light" size="sm" />
                      ) : (
                        <SendIcon className="h-4 w-4" />
                      )}
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </form>

      {/* Mention Menu */}
      {mentionProps && (
        <MentionMenu
          show={mentionProps.show}
          agents={mentionProps.agents}
          position={mentionProps.position}
          selectedIndex={mentionProps.selectedIndex}
          menuRef={mentionProps.menuRef}
          onAgentSelect={mentionProps.onAgentSelect}
        />
      )}

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        onChange={(_e) => {
          // This is a bit hacky, but we don't have a direct handler for file select
          // The parent component should handle this via fileInputRef
        }}
        className="hidden"
        accept="*/*"
      />
    </div>
  );
}
