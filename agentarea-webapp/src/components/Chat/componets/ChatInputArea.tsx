/**
 * Shared chat input area component
 * Supports text input, file attachments, and mentions
 */

import React from "react";
import { useTranslations } from "next-intl";
import {
  ArrowUp,
  FolderKanban,
  Loader2,
  Paperclip,
  Pause,
  Play,
  Send,
  ShieldCheck,
} from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import {
  TaskResourceAttach,
  type TaskResourceRef,
} from "@/components/ResourcePicker/TaskResourceAttach";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { AttachmentCard } from "@/components/ui/attachment-card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { MentionMenu } from "../MentionMenu";
import { ContextSelect } from "./ContextSelect";

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

  /** Keep drafting available while temporarily preventing submission. */
  isSubmitDisabled?: boolean;

  /**
   * Render the composer but let nothing be typed, attached or sent — for a
   * surface that shows where chatting will happen before it is possible.
   */
  disabled?: boolean;

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
   * File selection handler
   */
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;

  /** Optional delivery constraint shown when files are selected. */
  attachmentNotice?: string;

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

  /** Hide attachment controls on surfaces that cannot deliver files. */
  showAttachments?: boolean;

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
   
  };

  /**
   * Available agents (for agent selector)
   */
  availableAgents?: Array<{
    id: string;
    name: string;
    description?: string | null;
    icon?: string | null;
   
  }>;

  /**
   * Agent change handler
   */
  onAgentChange?: (agent: {
    id: string;
    name: string;
    description?: string | null;
    icon?: string | null;
   
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
   * MCP servers and skills attached to this run on top of the agent's own.
   * Present only where a task is being composed; absent leaves the control out.
   */
  taskMcps?: TaskResourceRef[];
  taskSkills?: TaskResourceRef[];
  onTaskMcpsChange?: (next: TaskResourceRef[]) => void;
  onTaskSkillsChange?: (next: TaskResourceRef[]) => void;

  /**
   * Shown at the start of the bottom row, before the agent/project/policy
   * selectors — e.g. a locked placeholder while no agent exists yet.
   */
  leadingControls?: React.ReactNode;

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
  isSubmitDisabled = false,
  disabled = false,
  placeholder,
  selectedFiles,
  onRemoveFile,
  onOpenFileDialog,
  onFileSelect,
  attachmentNotice,
  fileInputRef,
  textareaRef,
  onKeyDown,
  mentionProps,
  containerRef,
  variant: _variant = "default",
  showSendButton = true,
  showAttachments = true,
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
  taskMcps,
  taskSkills,
  onTaskMcpsChange,
  onTaskSkillsChange,
  leadingControls,
  onStop,
  onResume,
  isStopping = false,
  isResuming = false,
  canResume = false,
}: ChatInputAreaProps) {
  const t = useTranslations("Chat.inputControls");
  const SendIcon = sendButtonIcon === "arrow" ? ArrowUp : Send;
  const showContextControls =
    Boolean(leadingControls) ||
    Boolean(currentAgent && availableAgents?.length && onAgentChange) ||
    Boolean(availableProjects?.length && onProjectChange) ||
    Boolean(availableTaskPolicies?.length && onTaskPolicyChange);

  return (
    <div ref={containerRef} className={cn("w-full", containerClassName)}>
      <form
        onSubmit={onSubmit}
        className={cn(
          "relative flex flex-col overflow-hidden rounded-xl border border-border bg-background transition-colors focus-within:border-foreground/30 focus-within:ring-1 focus-within:ring-foreground/10",
          className
        )}
      >
        <Textarea
          ref={textareaRef}
          value={inputDisplay || input}
          onChange={onInputChange}
          placeholder={placeholder}
          disabled={isLoading || disabled}
          className="min-h-[48px] max-h-48 resize-none rounded-none border-0 bg-transparent px-4 pb-2 pt-3 text-[15px] leading-6 text-foreground shadow-none transition-none placeholder:text-muted-foreground/70 focus-visible:border-transparent dark:bg-transparent sm:min-h-[68px] sm:text-[13px] sm:leading-[21px]"
          rows={rows}
          onKeyDown={onKeyDown}
        />

        <div className="flex flex-col gap-2 px-2.5 pb-2.5">
          {/* Selected Files Display */}
          <div
            className={cn(
              "flex flex-row flex-wrap gap-2",
              selectedFiles.length === 0 && "hidden"
            )}
          >
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
          {selectedFiles.length > 0 && attachmentNotice ? (
            <p
              role="status"
              className="px-1 text-[11px] leading-4 text-muted-foreground"
            >
              {attachmentNotice}
            </p>
          ) : null}

          <div className="flex flex-wrap items-end gap-2 sm:flex-nowrap">
            {showContextControls ? (
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 overflow-hidden sm:flex-nowrap sm:gap-2">
                {leadingControls}
                {currentAgent && availableAgents?.length && onAgentChange ? (
                  <div className="min-w-0 basis-full sm:basis-auto">
                    {/* Trigger and options share one avatar. Rendering a bare
                        icon on the trigger dropped the hue, which is the part
                        that differs per agent — so picking another one left
                        the composer looking unchanged. */}
                    <ContextSelect
                      // Narrower than the other chips: agent names run long,
                      // and the project/policy defaults must stay readable.
                      className="min-w-0 sm:max-w-[12rem] sm:shrink"
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
                      renderTriggerIcon={(option) => (
                        <AgentAvatar
                          agent={option}
                          size="xs"
                          className="shrink-0"
                        />
                      )}
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

                {taskMcps && taskSkills && onTaskMcpsChange && onTaskSkillsChange ? (
                  <TaskResourceAttach
                    mcps={taskMcps}
                    skills={taskSkills}
                    onMcpsChange={onTaskMcpsChange}
                    onSkillsChange={onTaskSkillsChange}
                    disabled={isLoading}
                  />
                ) : null}
              </div>
            ) : (
              <div className="flex-1" />
            )}

            {/* Action Buttons */}
            <div className="ml-auto flex shrink-0 items-center justify-end gap-2">
              {showAttachments && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={onOpenFileDialog}
                  disabled={isLoading || disabled}
                  aria-label="Attach files"
                  className="h-8 w-8 rounded-md p-0 text-muted-foreground hover:bg-muted hover:text-foreground dark:hover:bg-muted"
                >
                  <Paperclip />
                </Button>
              )}

              {showSendButton && (
                <>
                  {canResume && onResume ? (
                    <Button
                      type="button"
                      size="icon"
                      variant="outline"
                      onClick={onResume}
                      disabled={isResuming}
                      aria-label="Resume"
                      className="h-8 w-8 rounded-md border-border text-foreground shadow-none hover:border-border hover:bg-muted hover:text-foreground"
                    >
                      {isResuming ? <LoadingSpinner size="sm" /> : <Play />}
                    </Button>
                  ) : isLoading && onStop ? (
                    <Button
                      type="button"
                      size="icon"
                      variant="destructive"
                      onClick={onStop}
                      disabled={isStopping}
                      aria-label="Pause"
                      className="h-8 w-8 rounded-md shadow-none"
                    >
                      {isStopping ? (
                        <LoadingSpinner variant="light" size="sm" />
                      ) : (
                        <Pause />
                      )}
                    </Button>
                  ) : (
                    <Button
                      type="submit"
                      size="icon"
                      aria-label="Send message"
                      disabled={
                        isLoading ||
                        isSubmitDisabled ||
                        disabled ||
                        (!input.trim() && selectedFiles.length === 0)
                      }
                      className="h-8 w-8 rounded-md bg-foreground text-background shadow-none hover:bg-foreground/85 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100"
                    >
                      {isLoading ? (
                        <Loader2
                          aria-hidden
                          className="animate-spin motion-reduce:animate-none"
                        />
                      ) : (
                        <SendIcon />
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
        onChange={onFileSelect}
        className="hidden"
        accept="*/*"
      />
    </div>
  );
}
