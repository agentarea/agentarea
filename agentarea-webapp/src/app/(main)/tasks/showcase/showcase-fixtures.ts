import type { A2UISurfaceState } from "@/lib/events/a2ui";
import type { Part } from "@/lib/events/contract";

export const richAnswer: Part = {
  partId: "showcase-answer",
  kind: "llm",
  eventType: "llm.call.completed",
  data: {
    content: `## Renderer inventory

This answer uses the **real Markdown renderer** with [a safe link](https://agentarea.dev), inline \`code\`, and a task list.

- [x] Message layout
- [x] Streaming-safe Markdown
- [x] Tables and code blocks

| State | Renderer | Result |
| --- | --- | --- |
| Complete | Streamdown | Stable |
| Streaming | Streamdown | Incremental |

\`\`\`ts
type ChatState = "running" | "waiting_for_input" | "completed";
const visible = states.filter((state) => state !== "hidden");
\`\`\`

> This route is deterministic: none of these controls call a model or tool.`,
  },
};

export const streamingAnswer: Part = {
  partId: "showcase-streaming",
  kind: "llm",
  eventType: "llm.call.chunk",
  data: {
    chunk:
      "I’m still composing this response. The current Markdown has **bold text**, a partial list, and an intentionally unfinished code fence:\n\n```tsx\nfunction StreamingPreview() {\n  return <",
  },
};

export const thinkingAnswer: Part = {
  partId: "showcase-thinking",
  kind: "llm",
  eventType: "llm.call.chunk",
  data: { chunk: "" },
};

export const toolParts: Part[] = [
  {
    partId: "tool-running",
    kind: "tool",
    eventType: "tool.call",
    data: {
      tool_name: "read_file",
      arguments: { path: "src/components/Chat/TaskConversation.tsx" },
    },
  },
  {
    partId: "tool-success",
    kind: "tool",
    eventType: "tool.result",
    data: {
      tool_name: "search_files",
      arguments: { query: "PartRenderer", path: "src" },
      result: "Found 7 matches across 5 files.",
      success: true,
      duration_ms: 184,
    },
  },
  {
    partId: "tool-shell-success",
    kind: "tool",
    eventType: "tool.result",
    data: {
      tool_name: "run_command",
      arguments: { command: "python3 score_leads.py --demo" },
      result:
        "Север Софт — 92 — назначить встречу\nМаяк Данные — 84 — уточнить бюджет\nВектор Лаб — 76 — отправить материалы",
      success: true,
      exit_code: 0,
      duration_ms: 246,
    },
  },
  {
    partId: "tool-artifacts",
    kind: "tool",
    eventType: "tool.result",
    data: {
      tool_name: "write_file",
      arguments: { path: "reports/chat-audit.md" },
      result: { bytes_written: 2840, status: "saved" },
      success: true,
      exit_code: 0,
      duration_ms: 92,
      artifact_paths: ["reports/chat-audit.md", "reports/chat-audit.json"],
    },
  },
  {
    partId: "tool-failed",
    kind: "tool",
    eventType: "tool.result",
    data: {
      tool_name: "run_command",
      arguments: { command: "pnpm test --filter missing-suite" },
      error: "No projects matched the filters in this workspace.",
      success: false,
      exit_code: 1,
      duration_ms: 311,
    },
  },
  {
    partId: "tool-unavailable",
    kind: "tool",
    eventType: "tool.result",
    data: {
      tool_name: "legacy_remote_tool",
      arguments: "[nested value omitted from event log]",
      result: "[omitted from event log: 2048 units]",
      success: true,
      execution_time: "[redacted]",
    },
  },
];

export const pendingInputPart: Part = {
  partId: "showcase-input",
  kind: "form",
  eventType: "input.request",
  data: {
    question: "Configure the release review",
    questions: [
      { id: "title", question: "Review title", type: "text", required: true },
      {
        id: "notes",
        question: "Success criteria",
        type: "textarea",
        required: true,
      },
      {
        id: "environment",
        question: "Environment",
        type: "select",
        options: ["Local", "Staging", "Production"],
        required: true,
      },
      {
        id: "checks",
        question: "Required checks",
        type: "multiselect",
        options: ["Accessibility", "Visual", "Performance"],
        required: true,
      },
      { id: "budget", question: "Time budget (minutes)", type: "number" },
      { id: "notify", question: "Notify when complete", type: "boolean" },
      {
        id: "token",
        question: "Temporary API token",
        type: "secret",
        secret_name: "showcase-token", // pragma: allowlist secret
        required: true,
      },
    ],
  },
};

export const resolvedInputPart: Part = {
  ...pendingInputPart,
  partId: "showcase-input-resolved",
  eventType: "input.response",
};

export const artifactParts: Part[] = [
  {
    partId: "artifact-pdf",
    kind: "artifact",
    eventType: "artifact.created",
    data: { name: "Chat review", path: "reports/chat-review.pdf" },
  },
  {
    partId: "artifact-image",
    kind: "artifact",
    eventType: "artifact.created",
    data: { name: "Conversation capture", path: "screenshots/chat-final.png" },
  },
  {
    partId: "artifact-unnamed",
    kind: "artifact",
    eventType: "artifact.updated",
    data: { name: "Artifact without a download path" },
  },
];

const imageData =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='640' height='180' viewBox='0 0 640 180'%3E%3Crect width='640' height='180' rx='16' fill='%23e4e4e7'/%3E%3Cpath d='M0 140L150 55l95 58 95-42 300 109H0z' fill='%23a1a1aa'/%3E%3Ccircle cx='510' cy='48' r='22' fill='%2371717a'/%3E%3Ctext x='24' y='36' font-family='sans-serif' font-size='18' fill='%233f3f46'%3EA2UI image fixture%3C/text%3E%3C/svg%3E";

export const a2uiSurface: A2UISurfaceState = {
  surface_id: "showcase-a2ui",
  catalog_id: "https://a2ui.org/specification/v0_9/basic_catalog.json",
  send_data_model: true,
  dataModel: {
    title: "A2UI basic catalog",
    description:
      "All 18 component types rendered by AgentArea’s current catalog.",
    owner: "Ada",
  },
  components: {
    root: {
      id: "root",
      component: "Column",
      children: [
        "title",
        "description",
        "divider",
        "display-card",
        "tabs",
        "form-card",
        "media-card",
        "modal",
      ],
    },
    title: {
      id: "title",
      component: "Text",
      variant: "h2",
      text: { path: "/title" },
    },
    description: {
      id: "description",
      component: "Text",
      text: { path: "/description" },
    },
    divider: { id: "divider", component: "Divider", axis: "horizontal" },
    "display-card": {
      id: "display-card",
      component: "Card",
      child: "display-column",
    },
    "display-column": {
      id: "display-column",
      component: "Column",
      children: ["display-heading", "icon-row", "sample-list"],
    },
    "display-heading": {
      id: "display-heading",
      component: "Text",
      variant: "h3",
      text: "Display and layout",
    },
    "icon-row": {
      id: "icon-row",
      component: "Row",
      align: "center",
      children: ["icon", "caption"],
    },
    icon: { id: "icon", component: "Icon", name: "sparkles" },
    caption: {
      id: "caption",
      component: "Text",
      variant: "caption",
      text: "Icon · Row · Column · List",
    },
    "sample-list": {
      id: "sample-list",
      component: "List",
      direction: "horizontal",
      children: ["list-one", "list-two", "list-three"],
    },
    "list-one": { id: "list-one", component: "Text", text: "Research" },
    "list-two": { id: "list-two", component: "Text", text: "Review" },
    "list-three": { id: "list-three", component: "Text", text: "Ship" },
    tabs: {
      id: "tabs",
      component: "Tabs",
      tabs: [
        { title: "Summary", child: "tab-summary" },
        { title: "Details", child: "tab-details" },
      ],
    },
    "tab-summary": {
      id: "tab-summary",
      component: "Text",
      text: "Tabs keep related agent output in one surface.",
    },
    "tab-details": {
      id: "tab-details",
      component: "Text",
      text: "This second tab is interactive local state.",
    },
    "form-card": { id: "form-card", component: "Card", child: "form-column" },
    "form-column": {
      id: "form-column",
      component: "Column",
      children: [
        "form-heading",
        "text-field",
        "check-box",
        "choice",
        "slider",
        "date-time",
        "action-button",
      ],
    },
    "form-heading": {
      id: "form-heading",
      component: "Text",
      variant: "h3",
      text: "Interactive controls",
    },
    "text-field": {
      id: "text-field",
      component: "TextField",
      label: "Owner",
      value: { path: "/owner" },
      placeholder: "Name",
    },
    "check-box": {
      id: "check-box",
      component: "CheckBox",
      label: "Include evidence",
      value: true,
    },
    choice: {
      id: "choice",
      component: "ChoicePicker",
      label: "Priority",
      options: [
        { label: "Normal", value: "normal" },
        { label: "Urgent", value: "urgent" },
      ],
    },
    slider: {
      id: "slider",
      component: "Slider",
      label: "Confidence",
      min: 0,
      max: 100,
      value: 82,
    },
    "date-time": {
      id: "date-time",
      component: "DateTimeInput",
      label: "Review at",
      enableDate: true,
      enableTime: true,
      value: "2026-09-19T10:30",
    },
    "action-label": {
      id: "action-label",
      component: "Text",
      text: "Run demo action",
    },
    "action-button": {
      id: "action-button",
      component: "Button",
      variant: "primary",
      child: "action-label",
      accessibility: { label: "Run local demo action" },
      action: {
        event: { name: "showcase.action", context: { source: "catalog" } },
      },
    },
    "media-card": {
      id: "media-card",
      component: "Card",
      child: "media-column",
    },
    "media-column": {
      id: "media-column",
      component: "Column",
      children: ["media-heading", "image", "video", "audio"],
    },
    "media-heading": {
      id: "media-heading",
      component: "Text",
      variant: "h3",
      text: "Media",
    },
    image: {
      id: "image",
      component: "Image",
      url: imageData,
      alt: "Abstract fixture landscape",
      fit: "cover",
    },
    video: { id: "video", component: "Video", url: "data:video/mp4;base64," },
    audio: {
      id: "audio",
      component: "AudioPlayer",
      url: "data:audio/mpeg;base64,",
      description: "AudioPlayer fixture (no network media)",
    },
    "modal-trigger-label": {
      id: "modal-trigger-label",
      component: "Text",
      text: "Open modal",
    },
    "modal-trigger": {
      id: "modal-trigger",
      component: "Button",
      variant: "default",
      child: "modal-trigger-label",
      accessibility: { label: "Open A2UI modal" },
    },
    "modal-content": {
      id: "modal-content",
      component: "Text",
      variant: "h3",
      text: "This is the Modal component.",
    },
    modal: {
      id: "modal",
      component: "Modal",
      trigger: "modal-trigger",
      content: "modal-content",
    },
  },
};

export const a2uiPart: Part = {
  partId: a2uiSurface.surface_id,
  kind: "a2ui",
  eventType: "a2ui.update.components",
  data: { surface: a2uiSurface },
};
