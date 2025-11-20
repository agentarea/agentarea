"use client";

import React, { useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from "react";
import { cn } from "@/lib/utils";
import { parseMentions } from "@/utils/mentions";

interface MentionTextareaProps
  extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "onChange" | "value"> {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

export interface MentionTextareaHandle {
  focus: () => void;
  setSelectionRange: (start: number, end: number) => void;
  selectionStart: number;
}

export const MentionTextarea = forwardRef<MentionTextareaHandle, MentionTextareaProps>(
  ({ value, onChange, className, placeholder, disabled, ...props }, ref) => {
    const contentEditableRef = useRef<HTMLDivElement>(null);
    const isUpdatingRef = useRef(false);

    // Expose methods via ref
    useImperativeHandle(ref, () => ({
      focus: () => {
        contentEditableRef.current?.focus();
      },
      setSelectionRange: (start: number, end: number) => {
        const selection = window.getSelection();
        if (!selection || !contentEditableRef.current) return;

        const range = document.createRange();
        const walker = document.createTreeWalker(
          contentEditableRef.current,
          NodeFilter.SHOW_TEXT,
          null
        );

        let currentPos = 0;
        let startNode: Node | null = null;
        let endNode: Node | null = null;
        let startOffset = 0;
        let endOffset = 0;

        while (walker.nextNode()) {
          const node = walker.currentNode;
          const textLength = node.textContent?.length || 0;

          if (!startNode && currentPos + textLength >= start) {
            startNode = node;
            startOffset = start - currentPos;
          }

          if (!endNode && currentPos + textLength >= end) {
            endNode = node;
            endOffset = end - currentPos;
            break;
          }

          currentPos += textLength;
        }

        if (startNode && endNode) {
          range.setStart(startNode, startOffset);
          range.setEnd(endNode, endOffset);
          selection.removeAllRanges();
          selection.addRange(range);
        }
      },
      get selectionStart() {
        const selection = window.getSelection();
        if (!selection || !contentEditableRef.current) return 0;

        const range = selection.getRangeAt(0);
        const preCaretRange = range.cloneRange();
        preCaretRange.selectNodeContents(contentEditableRef.current);
        preCaretRange.setEnd(range.endContainer, range.endOffset);

        return preCaretRange.toString().length;
      },
    }));

  // Render text with mentions highlighted
  const renderContent = useCallback((text: string): string => {
    if (!text) return "";
    
    const mentions = parseMentions(text);
    if (mentions.length === 0) {
      // Escape HTML
      return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>");
    }

    let html = "";
    let lastIndex = 0;

    mentions.forEach((mention) => {
      // Add text before mention
      const beforeText = text.substring(lastIndex, mention.start);
      html += beforeText
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\n/g, "<br>");

      // Add mention as highlighted span
      const mentionText = text.substring(mention.start, mention.end);
      html += `<span class="mention-tag" data-mention-id="${mention.agentId}" contenteditable="false">${mentionText.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</span>`;

      lastIndex = mention.end;
    });

    // Add remaining text
    const afterText = text.substring(lastIndex);
    html += afterText
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\n/g, "<br>");

    return html;
  }, []);

  // Update content when value changes externally
  useEffect(() => {
    if (!contentEditableRef.current || isUpdatingRef.current) return;

    const currentHtml = contentEditableRef.current.innerHTML;
    const newHtml = renderContent(value);

    if (currentHtml !== newHtml) {
      isUpdatingRef.current = true;
      const selection = window.getSelection();
      const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
      const savedRange = range
        ? {
            startContainer: range.startContainer,
            startOffset: range.startOffset,
            endContainer: range.endContainer,
            endOffset: range.endOffset,
          }
        : null;

      contentEditableRef.current.innerHTML = newHtml;

      // Restore cursor position
      if (savedRange && selection) {
        try {
          const newRange = document.createRange();
          newRange.setStart(savedRange.startContainer, savedRange.startOffset);
          newRange.setEnd(savedRange.endContainer, savedRange.endOffset);
          selection.removeAllRanges();
          selection.addRange(newRange);
        } catch (e) {
          // Ignore errors
        }
      }

      setTimeout(() => {
        isUpdatingRef.current = false;
      }, 0);
    }
  }, [value, renderContent]);

  // Handle input and extract plain text
  const handleInput = useCallback(() => {
    if (!contentEditableRef.current || isUpdatingRef.current) return;

    const html = contentEditableRef.current.innerHTML;
    
    // Convert HTML back to plain text with mentions
    let text = "";
    const walker = document.createTreeWalker(
      contentEditableRef.current,
      NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
      null
    );

    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === Node.TEXT_NODE) {
        text += node.textContent || "";
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        const element = node as HTMLElement;
        if (element.classList.contains("mention-tag")) {
          text += element.textContent || "";
        } else if (element.tagName === "BR") {
          text += "\n";
        }
      }
    }

    // Replace newlines from BR tags
    text = text.replace(/\n+/g, "\n");

    isUpdatingRef.current = true;
    onChange(text);
    setTimeout(() => {
      isUpdatingRef.current = false;
    }, 0);
  }, [onChange]);

  // Handle keydown to prevent partial deletion of mentions
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const selection = window.getSelection();
    if (!selection || !contentEditableRef.current) return;

    // Handle Backspace and Delete
    if (e.key === "Backspace" || e.key === "Delete") {
      const range = selection.getRangeAt(0);
      const mentionElement = range.startContainer.parentElement?.closest(".mention-tag") as HTMLElement;

      if (mentionElement) {
        e.preventDefault();
        // Delete entire mention
        mentionElement.remove();
        handleInput();
      }
    }
  }, [handleInput]);

  return (
    <>
      <div
        ref={contentEditableRef}
        contentEditable
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        className={cn(
          "min-h-auto h-auto resize-none border-none pb-0 pr-12 pt-3 transition-all duration-700 ease-out",
          "focus:outline-none whitespace-pre-wrap break-words",
          className
        )}
        style={{
          minHeight: "auto",
        }}
        data-placeholder={placeholder}
        suppressContentEditableWarning
        {...(props as any)}
      />
      <style>{`
        [contenteditable][data-placeholder]:empty:before {
          content: attr(data-placeholder);
          color: #9ca3af;
          pointer-events: none;
        }
        .mention-tag {
          display: inline-block;
          background-color: rgb(59 130 246 / 0.1);
          color: rgb(59 130 246);
          font-weight: 500;
          padding: 2px 4px;
          border-radius: 4px;
          margin: 0 1px;
          user-select: none;
        }
        .mention-tag[contenteditable="false"] {
          cursor: default;
        }
      `}</style>
    </>
  );
});

MentionTextarea.displayName = "MentionTextarea";

