"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, RotateCcw } from "lucide-react";
import ActivityGroup from "@/components/Chat/ActivityGroup";
import ApprovalRequestMessage from "@/components/Chat/componets/ApprovalRequestMessage";
import { ChatInputArea } from "@/components/Chat/componets/ChatInputArea";
import UserMessage from "@/components/Chat/componets/UserMessage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import { cn } from "@/lib/utils";
import {
  a2uiPart,
  artifactParts,
  pendingInputPart,
  resolvedInputPart,
  richAnswer,
  streamingAnswer,
  thinkingAnswer,
  toolParts,
} from "./showcase-fixtures";

const scenarios = [
  { id: "conversation", label: "Conversation" },
  { id: "tools", label: "Tools & activity" },
  { id: "human", label: "Human controls" },
  { id: "artifacts", label: "Artifacts" },
  { id: "a2ui", label: "A2UI catalog" },
] as const;

type Scenario = (typeof scenarios)[number]["id"];

interface LocalMessage {
  content: string;
  files: File[];
  timestamp: string;
}

const coverage: Record<Scenario, string[]> = {
  conversation: [
    "User avatar",
    "Attachments",
    "Rich Markdown",
    "Streaming",
    "Thinking",
    "Composer",
  ],
  tools: [
    "Pending",
    "Success",
    "Failure",
    "Artifacts",
    "Unavailable detail",
    "Completed group",
  ],
  human: ["7 input types", "Pending/resolved", "Approval", "Continuation"],
  artifacts: ["PDF", "Image", "Named artifact", "Updated artifact"],
  a2ui: [
    "18 basic catalog components",
    "Data binding",
    "Action",
    "Tabs",
    "Modal",
  ],
};

function makeDemoFiles(): File[] {
  if (typeof File === "undefined") return [];
  return [
    new File(
      ["# Chat audit\nDeterministic showcase attachment."],
      "chat-audit.md",
      {
        type: "text/markdown",
      }
    ),
    new File(["%PDF-1.4\n% demo"], "renderer-inventory.pdf", {
      type: "application/pdf",
    }),
    new File(
      [
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="96"><rect width="160" height="96" rx="12" fill="#e4e4e7"/><path d="M0 78 48 32l38 31 25-18 49 51H0z" fill="#71717a"/></svg>',
      ],
      "conversation-preview.svg",
      { type: "image/svg+xml" }
    ),
  ];
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
      <span>{children}</span>
      <span aria-hidden className="h-px flex-1 bg-border/70" />
    </div>
  );
}

export default function ChatRendererShowcase() {
  const [scenario, setScenario] = useState<Scenario>("conversation");
  const [messageFiles, setMessageFiles] = useState<File[]>([]);
  const [composerFiles, setComposerFiles] = useState<File[]>([]);
  const [input, setInput] = useState("Review the renderer inventory");
  const [localMessages, setLocalMessages] = useState<LocalMessage[]>([]);
  const [canResume, setCanResume] = useState(true);
  const [formResolved, setFormResolved] = useState(false);
  const [demoRevision, setDemoRevision] = useState(0);
  const [announcement, setAnnouncement] = useState("No demo interaction yet.");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const demoFiles = makeDemoFiles();
    setMessageFiles(demoFiles);
    setComposerFiles(demoFiles);
  }, []);

  const completedRun = useMemo(
    () => ({
      id: "showcase-completed-run",
      parts: toolParts.slice(1),
      completed: true,
      terminalType: "task.completed",
      actionCount: toolParts.length - 1,
      errorCount: 1,
    }),
    []
  );

  const handleComposerSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!input.trim() && composerFiles.length === 0) return;
    setLocalMessages((messages) => [
      ...messages,
      {
        content: input.trim() || "Sent attachments",
        files: [...composerFiles],
        timestamp: new Date().toISOString(),
      },
    ]);
    setAnnouncement(
      `Local composer submitted ${composerFiles.length} attachment${composerFiles.length === 1 ? "" : "s"}.`
    );
    setInput("");
    setComposerFiles([]);
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b bg-muted/20 px-4 py-3 md:px-6">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-sm font-semibold text-foreground">
                All chat renderers
              </h1>
              <p className="mt-0.5 max-w-2xl text-xs leading-5 text-muted-foreground">
                A deterministic demo task built from production components.
                Interactions update local state only; no model, tool, upload, or
                API request runs here.
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                const demoFiles = makeDemoFiles();
                setMessageFiles(demoFiles);
                setComposerFiles(demoFiles);
                setInput("Review the renderer inventory");
                setLocalMessages([]);
                setCanResume(true);
                setFormResolved(false);
                setDemoRevision((revision) => revision + 1);
                setAnnouncement("Showcase reset.");
              }}
            >
              <RotateCcw aria-hidden className="h-3.5 w-3.5" />
              Reset demo
            </Button>
          </div>

          <div
            role="tablist"
            aria-label="Renderer scenarios"
            className="flex gap-1 overflow-x-auto"
          >
            {scenarios.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={scenario === item.id}
                aria-controls="showcase-panel"
                onClick={() => setScenario(item.id)}
                className={cn(
                  "shrink-0 rounded-md px-3 py-1.5 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                  scenario === item.id
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div
            className="flex flex-wrap gap-1.5"
            aria-label="Visible renderer coverage"
          >
            {coverage[scenario].map((item) => (
              <Badge key={item} variant="outline" className="font-normal">
                <Check aria-hidden className="mr-1 h-3 w-3" />
                {item}
              </Badge>
            ))}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div
          key={demoRevision}
          id="showcase-panel"
          role="tabpanel"
          tabIndex={0}
          className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6 md:px-6"
        >
          {scenario === "conversation" ? (
            <>
              <SectionLabel>User message with attachments</SectionLabel>
              <UserMessage
                id="showcase-user"
                content="Please audit this chat renderer and keep the attachments available in the composer."
                timestamp="2026-09-19T09:30:00.000Z"
                files={messageFiles}
              />
              {localMessages.map((message, index) => (
                <UserMessage
                  key={`${message.timestamp}-${index}`}
                  id={`showcase-local-${index}`}
                  content={message.content}
                  timestamp={message.timestamp}
                  files={message.files}
                />
              ))}
              <SectionLabel>Complete rich answer</SectionLabel>
              <PartRenderer part={richAnswer} />
              <SectionLabel>Streaming answer</SectionLabel>
              <PartRenderer part={streamingAnswer} />
              <SectionLabel>Empty streaming state</SectionLabel>
              <PartRenderer part={thinkingAnswer} />
            </>
          ) : null}

          {scenario === "tools" ? (
            <>
              <SectionLabel>Independent tool states</SectionLabel>
              {toolParts.map((part) => (
                <PartRenderer key={part.partId} part={part} />
              ))}
              <SectionLabel>
                Completed activity group and final output
              </SectionLabel>
              <ActivityGroup run={completedRun} />
              <PartRenderer part={richAnswer} />
            </>
          ) : null}

          {scenario === "human" ? (
            <>
              <SectionLabel>Structured input request</SectionLabel>
              <PartRenderer
                key={
                  formResolved
                    ? resolvedInputPart.partId
                    : pendingInputPart.partId
                }
                part={formResolved ? resolvedInputPart : pendingInputPart}
                onFormSubmit={(id, answers, secrets) => {
                  setFormResolved(true);
                  setAnnouncement(
                    `Submitted ${id}: ${Object.keys(answers).length} answers and ${Object.keys(secrets).length} secret reference.`
                  );
                }}
              />
              <SectionLabel>Interactive approval</SectionLabel>
              <ApprovalRequestMessage
                data={{
                  escalation_id: "showcase-approval",
                  tool_name: "deploy_preview",
                  tool_call_id: "showcase-deploy",
                  arguments: { environment: "staging", revision: "demo-only" },
                  message:
                    "Approve the local demonstration of an action requiring confirmation.",
                  _onResolve: (_id, approved, comment) =>
                    setAnnouncement(
                      approved
                        ? "Demo approval accepted."
                        : `Demo approval denied${comment ? `: ${comment}` : "."}`
                    ),
                }}
              />
              <SectionLabel>Awaiting continuation</SectionLabel>
              <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                The task reached its turn limit. The composer below exposes the
                production Resume control with local state.
              </div>
            </>
          ) : null}

          {scenario === "artifacts" ? (
            <>
              <SectionLabel>Artifact events</SectionLabel>
              {artifactParts.map((part) => (
                <PartRenderer key={part.partId} part={part} />
              ))}
              <SectionLabel>Tool-produced artifacts</SectionLabel>
              <PartRenderer part={toolParts[2]} />
              <p className="text-xs leading-5 text-muted-foreground">
                The current artifact renderer exposes the real file chip state.
                Inline image preview belongs to user attachments and appears in
                the Conversation scenario.
              </p>
            </>
          ) : null}

          {scenario === "a2ui" ? (
            <>
              <SectionLabel>A2UI v0.9 basic catalog</SectionLabel>
              <PartRenderer
                part={a2uiPart}
                onA2UIAction={(action, surfaceId, componentId, context) =>
                  setAnnouncement(
                    `A2UI action from ${surfaceId}/${componentId}: ${action.event?.name ?? action.functionCall?.call ?? "unknown"}. ${JSON.stringify(context)}`
                  )
                }
              />
            </>
          ) : null}

          <p className="sr-only" aria-live="polite">
            {announcement}
          </p>
          <div
            className="rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
            aria-hidden
          >
            Demo event: {announcement}
          </div>
        </div>
      </div>

      <div className="shrink-0 border-t bg-background px-4 py-3 md:px-6">
        <div className="mx-auto w-full max-w-3xl">
          <ChatInputArea
            input={input}
            onInputChange={(event) => setInput(event.target.value)}
            onSubmit={handleComposerSubmit}
            isLoading={false}
            placeholder="Send a local showcase message…"
            selectedFiles={composerFiles}
            onRemoveFile={(index) =>
              setComposerFiles((current) =>
                current.filter((_, itemIndex) => itemIndex !== index)
              )
            }
            onOpenFileDialog={() => fileInputRef.current?.click()}
            onFileSelect={(event) => {
              const selected = Array.from(event.target.files ?? []);
              if (selected.length === 0) return;
              setComposerFiles((current) => [...current, ...selected]);
              setAnnouncement(
                `Added ${selected.length} local attachment${selected.length === 1 ? "" : "s"}.`
              );
              event.target.value = "";
            }}
            fileInputRef={fileInputRef}
            textareaRef={textareaRef}
            sendButtonIcon="send"
            rows={1}
            canResume={scenario === "human" && canResume}
            onResume={() => {
              setCanResume(false);
              setAnnouncement("Demo task resumed locally.");
            }}
          />
        </div>
      </div>
    </div>
  );
}
