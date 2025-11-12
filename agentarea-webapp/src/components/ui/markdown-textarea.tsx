"use client";

import { useEditor, EditorContent, Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import { useEffect, useRef, useMemo } from "react";
import { cn } from "@/lib/utils";
import { marked } from "marked";
import TurndownService from "turndown";
import "./markdown-textarea.css";

interface MarkdownTextareaProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  id?: string;
  "aria-invalid"?: boolean;
}

// Convert markdown to HTML for display
function markdownToHtml(markdown: string): string {
  try {
    return marked.parse(markdown, { breaks: true, gfm: true }) as string;
  } catch {
    return markdown;
  }
}

// Create Turndown service instance (only in browser)
let turndownService: TurndownService | null = null;

function getTurndownService(): TurndownService | null {
  if (typeof window === "undefined") return null;
  
  if (!turndownService) {
    turndownService = new TurndownService({
      headingStyle: "atx",
      bulletListMarker: "-",
      codeBlockStyle: "fenced",
      emDelimiter: "*",
      strongDelimiter: "**",
    });
  }
  
  return turndownService;
}

// Extract text from HTML (fallback)
function extractTextFromHtml(html: string): string {
  if (typeof document === "undefined") return "";
  const div = document.createElement("div");
  div.innerHTML = html;
  return div.textContent || div.innerText || "";
}

// Convert HTML to markdown for saving
function htmlToMarkdown(html: string): string {
  if (!html || html.trim() === "" || html === "<p></p>") {
    return "";
  }
  
  const service = getTurndownService();
  if (!service) {
    return extractTextFromHtml(html);
  }
  
  try {
    let markdown = service.turndown(html);
    markdown = markdown.replace(/\n{3,}/g, "\n\n");
    return markdown.trim();
  } catch {
    return extractTextFromHtml(html);
  }
}

// Check if text contains markdown syntax
function hasMarkdownSyntax(text: string): boolean {
  return (
    /^#{1,6}[\s\S]/.test(text.trim()) ||
    /\*\*[^*]+\*\*/.test(text) ||
    /\*[^*\*]+\*/.test(text) ||
    /`[^`]+`/.test(text) ||
    /^[-*+]\s/m.test(text) ||
    /^\d+\.\s/m.test(text)
  );
}

const EMPTY_HTML = "<p></p>";
const UPDATE_DELAY = 50;
const RESET_DELAY = 100;

export function MarkdownTextarea({
  value,
  onChange,
  placeholder = "",
  className,
  id,
  "aria-invalid": ariaInvalid,
}: MarkdownTextareaProps) {
  const isUpdatingRef = useRef(false);

  const placeholderExtension = useMemo(
    () =>
      Placeholder.configure({
        placeholder: ({ editor }) => {
          return editor.isEmpty ? (placeholder || "") : "";
        },
        showOnlyWhenEditable: true,
        showOnlyCurrent: false,
      }),
    [placeholder]
  );

  const editor = useEditor({
    extensions: [StarterKit, placeholderExtension],
    content: "",
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: cn(
          "markdown-editor-content focus:outline-none",
          className
        ),
      },
      handleKeyDown: (view, event) => {
        if (event.key !== " " && event.key !== "Enter") return false;
        if (!editor) return false;
        
        const { state } = view;
        const { selection } = state;
        const { $from } = selection;
        
        const lineStart = $from.start($from.depth);
        const lineEnd = $from.end($from.depth);
        const lineText = state.doc.textBetween(lineStart, lineEnd, "\n");
        
        // Check for markdown heading syntax
        const headingMatch = lineText.match(/^(#{1,6})\s+(.+)$/);
        if (headingMatch) {
          event.preventDefault();
          isUpdatingRef.current = true;
          
          setTimeout(() => {
            editor.chain()
              .focus()
              .setTextSelection({ from: lineStart, to: lineEnd })
              .deleteSelection()
              .setHeading({ level: headingMatch[1].length as 1 | 2 | 3 | 4 | 5 | 6 })
              .insertContent(headingMatch[2])
              .run();
            
            setTimeout(() => {
              isUpdatingRef.current = false;
            }, RESET_DELAY);
          }, 0);
          
          return true;
        }
        
        // Check for ordered list syntax (only on Space)
        if (event.key === " ") {
          const orderedListMatch = lineText.match(/^(\d+)\.\s+(.*)$/);
          if (orderedListMatch) {
            event.preventDefault();
            isUpdatingRef.current = true;
            
            setTimeout(() => {
              editor.chain()
                .focus()
                .setTextSelection({ from: lineStart, to: lineEnd })
                .deleteSelection()
                .toggleOrderedList()
                .insertContent(orderedListMatch[2] || " ")
                .run();
              
              setTimeout(() => {
                isUpdatingRef.current = false;
              }, RESET_DELAY);
            }, 0);
            
            return true;
          }
          
          // Check for unordered list syntax
          const unorderedListMatch = lineText.match(/^([-*+])\s+(.+)$/);
          if (unorderedListMatch) {
            event.preventDefault();
            isUpdatingRef.current = true;
            
            setTimeout(() => {
              editor.chain()
                .focus()
                .setTextSelection({ from: lineStart, to: lineEnd })
                .deleteSelection()
                .toggleBulletList()
                .insertContent(unorderedListMatch[2])
                .run();
              
              setTimeout(() => {
                isUpdatingRef.current = false;
              }, RESET_DELAY);
            }, 0);
            
            return true;
          }
        }
        
        return false;
      },
      handlePaste: (view, event) => {
        const text = event.clipboardData?.getData("text/plain");
        if (!text || !hasMarkdownSyntax(text)) return false;
        if (!editor) return false;
        
        event.preventDefault();
        isUpdatingRef.current = true;
        
        setTimeout(() => {
          editor.chain()
            .focus()
            .insertContent(markdownToHtml(text))
            .run();
          
          setTimeout(() => {
            isUpdatingRef.current = false;
          }, RESET_DELAY);
        }, 0);
        
        return true;
      },
    },
    onUpdate: ({ editor }) => {
      if (isUpdatingRef.current) return;
      const html = editor.getHTML();
      // Convert HTML to markdown before saving
      const markdown = htmlToMarkdown(html);
      onChange(markdown);
    },
  });


  // Update editor when value changes externally
  useEffect(() => {
    if (!editor || isUpdatingRef.current) return;
    
    // Value is always markdown, convert to HTML for editor display
    const htmlContent = value ? markdownToHtml(value) : EMPTY_HTML;
    const currentHtml = editor.getHTML();
    
    // Convert current HTML to markdown for comparison
    const currentMarkdown = htmlToMarkdown(currentHtml);
    
    // Only update if markdown content actually changed
    if (value !== currentMarkdown && htmlContent !== EMPTY_HTML) {
      isUpdatingRef.current = true;
      editor.commands.setContent(htmlContent || EMPTY_HTML);
      
      setTimeout(() => {
        isUpdatingRef.current = false;
      }, UPDATE_DELAY);
    }
  }, [value, editor]);

  useEffect(() => {
    if (!editor) return;
    
    const dom = editor.view.dom;
    if (ariaInvalid) {
      dom.setAttribute("aria-invalid", "true");
    } else {
      dom.removeAttribute("aria-invalid");
    }
  }, [editor, ariaInvalid]);


  if (!editor) {
    return null;
  }

  return (
    <div
      className={cn(
        "markdown-editor-wrapper flex min-h-[60px] w-full rounded-md border border-input bg-white px-3 py-2 pr-[2px] text-base text-inputSize outline-none ring-0 transition-all duration-300 placeholder:text-muted-foreground focus:ring-0 focus-visible:border-primary focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-900 focus-visible:dark:border-accent-foreground",
        className
      )}
      id={id}
    >
      <EditorContent editor={editor} />
    </div>
  );
}

