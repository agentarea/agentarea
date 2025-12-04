/**
 * Shared chat input area component
 * Supports text input, file attachments, and mentions
 */

import React from "react";
import { Paperclip, ArrowUp, Send } from "lucide-react";
import { AttachmentCard } from "@/components/ui/attachment-card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { cn } from "@/lib/utils";
import { MentionMenu } from "../MentionMenu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface MentionMenuProps {
  show: boolean;
  agents: Array<{ id: string; name: string; description?: string | null }>;
  position: { top: number; left: number };
  selectedIndex: number;
  menuRef: React.RefObject<HTMLDivElement>;
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
  fileInputRef: React.RefObject<HTMLInputElement>;

  /**
   * Textarea ref
   */
  textareaRef: React.RefObject<HTMLTextAreaElement>;

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
  containerRef?: React.RefObject<HTMLDivElement>;

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
  };

  /**
   * Available agents (for agent selector)
   */
  availableAgents?: Array<{
    id: string;
    name: string;
    description?: string | null;
  }>;

  /**
   * Agent change handler
   */
  onAgentChange?: (agent: {
    id: string;
    name: string;
    description?: string | null;
  }) => void;
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
}: ChatInputAreaProps) {
  const SendIcon = sendButtonIcon === "arrow" ? ArrowUp : Send;

  return (
    <div
      ref={containerRef}
      className={cn(
        "w-full",
        variant === "centered" && "mx-auto max-w-3xl",
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

        {/* Agent Selector */}
        {availableAgents && availableAgents.length > 1 && currentAgent && onAgentChange && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Agent:</span>
            <Select
              value={currentAgent.id}
              onValueChange={(agentId) => {
                const agent = availableAgents.find((a) => a.id === agentId);
                if (agent) {
                  onAgentChange(agent);
                }
              }}
            >
              <SelectTrigger className="h-8 w-48 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {availableAgents.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <div className="flex items-center justify-between gap-2">
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

          {/* Action Buttons */}
          <div className="flex items-center gap-2">
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
              <Button
                type="submit"
                size="icon"
                disabled={
                  isLoading || (!input.trim() && selectedFiles.length === 0)
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
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          // This is a bit hacky, but we don't have a direct handler for file select
          // The parent component should handle this via fileInputRef
        }}
        className="hidden"
        accept="*/*"
      />
    </div>
  );
}
