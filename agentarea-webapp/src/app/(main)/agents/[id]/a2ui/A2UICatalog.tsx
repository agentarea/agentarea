"use client";

import React from "react";
import A2UIMessage from "@/components/Chat/componets/A2UIMessage";
import type { A2UIComponent, A2UISurfaceData } from "@/components/Chat/types";

// ── Component catalog definitions ────────────────────────────────────────────

interface CatalogEntry {
  title: string;
  category: "Display" | "Layout" | "Container" | "Interactive";
  description: string;
  components: Record<string, A2UIComponent>;
  dataModel?: Record<string, any>;
}

const CATALOG: CatalogEntry[] = [
  // ── Display ──────────────────────────────────────────────────────────────
  {
    title: "Text",
    category: "Display",
    description: "Renders text with variant styling (h1–h5, body, caption).",
    components: {
      root: {
        id: "root",
        component: "Column",
        children: ["h1", "h3", "body", "caption"],
      },
      h1: { id: "h1", component: "Text", variant: "h1", text: "Heading 1" },
      h3: { id: "h3", component: "Text", variant: "h3", text: "Heading 3" },
      body: { id: "body", component: "Text", variant: "body", text: "Body text renders in the default style." },
      caption: { id: "caption", component: "Text", variant: "caption", text: "Caption text is small and muted." },
    },
  },
  {
    title: "Image",
    category: "Display",
    description: "Displays an image with URL sanitization and object-fit control.",
    components: {
      root: {
        id: "root",
        component: "Image",
        url: "https://placehold.co/400x200/e2e8f0/64748b?text=A2UI+Image",
        alt: "Sample image",
        fit: "cover",
      },
    },
  },
  {
    title: "Icon",
    category: "Display",
    description: "Renders a named icon placeholder.",
    components: {
      root: {
        id: "root",
        component: "Row",
        children: ["icon1", "icon2", "icon3"],
      },
      icon1: { id: "icon1", component: "Icon", name: "star" },
      icon2: { id: "icon2", component: "Icon", name: "heart" },
      icon3: { id: "icon3", component: "Icon", name: "settings" },
    },
  },
  {
    title: "Video",
    category: "Display",
    description: "Embedded video player with native controls.",
    components: {
      root: {
        id: "root",
        component: "Video",
        url: "https://placehold.co/400x200/e2e8f0/64748b?text=Video+Player",
      },
    },
  },
  {
    title: "AudioPlayer",
    category: "Display",
    description: "Audio player with optional description text.",
    components: {
      root: {
        id: "root",
        component: "AudioPlayer",
        description: "Sample audio track",
        url: "",
      },
    },
  },
  {
    title: "Divider",
    category: "Display",
    description: "Horizontal or vertical separator line.",
    components: {
      root: {
        id: "root",
        component: "Column",
        children: ["label1", "hr", "label2"],
      },
      label1: { id: "label1", component: "Text", variant: "body", text: "Content above" },
      hr: { id: "hr", component: "Divider", axis: "horizontal" },
      label2: { id: "label2", component: "Text", variant: "body", text: "Content below" },
    },
  },
  // ── Layout ───────────────────────────────────────────────────────────────
  {
    title: "Row",
    category: "Layout",
    description: "Horizontal flex container with justify/align options.",
    components: {
      root: {
        id: "root",
        component: "Row",
        justify: "spaceAround",
        align: "center",
        children: ["a", "b", "c"],
      },
      a: { id: "a", component: "Text", variant: "body", text: "Item A" },
      b: { id: "b", component: "Text", variant: "body", text: "Item B" },
      c: { id: "c", component: "Text", variant: "body", text: "Item C" },
    },
  },
  {
    title: "Column",
    category: "Layout",
    description: "Vertical flex container with justify/align options.",
    components: {
      root: {
        id: "root",
        component: "Column",
        justify: "start",
        align: "start",
        children: ["a", "b", "c"],
      },
      a: { id: "a", component: "Text", variant: "body", text: "Row 1" },
      b: { id: "b", component: "Text", variant: "body", text: "Row 2" },
      c: { id: "c", component: "Text", variant: "body", text: "Row 3" },
    },
  },
  {
    title: "List",
    category: "Layout",
    description: "Unordered list with horizontal or vertical direction.",
    components: {
      root: {
        id: "root",
        component: "List",
        direction: "vertical",
        children: ["i1", "i2", "i3"],
      },
      i1: { id: "i1", component: "Text", variant: "body", text: "First item" },
      i2: { id: "i2", component: "Text", variant: "body", text: "Second item" },
      i3: { id: "i3", component: "Text", variant: "body", text: "Third item" },
    },
  },
  // ── Container ────────────────────────────────────────────────────────────
  {
    title: "Card",
    category: "Container",
    description: "Bordered card container with padding and shadow.",
    components: {
      root: {
        id: "root",
        component: "Card",
        child: "content",
      },
      content: {
        id: "content",
        component: "Column",
        children: ["title", "body"],
      },
      title: { id: "title", component: "Text", variant: "h4", text: "Card Title" },
      body: { id: "body", component: "Text", variant: "body", text: "This is the card body content. Cards wrap children with a border, padding, and shadow." },
    },
  },
  {
    title: "Tabs",
    category: "Container",
    description: "Tab container with switchable content panels.",
    components: {
      root: {
        id: "root",
        component: "Tabs",
        tabs: [
          { title: "Overview", child: "tab1" },
          { title: "Details", child: "tab2" },
        ],
      },
      tab1: { id: "tab1", component: "Text", variant: "body", text: "Overview content goes here." },
      tab2: { id: "tab2", component: "Text", variant: "body", text: "Detailed information goes here." },
    },
  },
  {
    title: "Modal",
    category: "Container",
    description: "Modal dialog with trigger element and overlay content.",
    components: {
      root: {
        id: "root",
        component: "Modal",
        trigger: "trigger-btn",
        content: "modal-body",
      },
      "trigger-btn": { id: "trigger-btn", component: "Text", variant: "body", text: "Click to open modal" },
      "modal-body": {
        id: "modal-body",
        component: "Column",
        children: ["modal-title", "modal-text"],
      },
      "modal-title": { id: "modal-title", component: "Text", variant: "h3", text: "Modal Title" },
      "modal-text": { id: "modal-text", component: "Text", variant: "body", text: "This is modal content. Click the X to close." },
    },
  },
  // ── Interactive ──────────────────────────────────────────────────────────
  {
    title: "Button",
    category: "Interactive",
    description: "Clickable button with variants: default, primary, borderless.",
    components: {
      root: {
        id: "root",
        component: "Row",
        children: ["btn-default", "btn-primary", "btn-borderless"],
      },
      "btn-default": {
        id: "btn-default",
        component: "Button",
        variant: "default",
        child: "btn-default-label",
      },
      "btn-default-label": { id: "btn-default-label", component: "Text", text: "Default" },
      "btn-primary": {
        id: "btn-primary",
        component: "Button",
        variant: "primary",
        child: "btn-primary-label",
      },
      "btn-primary-label": { id: "btn-primary-label", component: "Text", text: "Primary" },
      "btn-borderless": {
        id: "btn-borderless",
        component: "Button",
        variant: "borderless",
        child: "btn-borderless-label",
      },
      "btn-borderless-label": { id: "btn-borderless-label", component: "Text", text: "Borderless" },
    },
  },
  {
    title: "TextField",
    category: "Interactive",
    description: "Input field with variants: shortText, longText, number, obscured.",
    components: {
      root: {
        id: "root",
        component: "Column",
        children: ["short", "long", "num"],
      },
      short: {
        id: "short",
        component: "TextField",
        variant: "shortText",
        label: "Short text",
        placeholder: "Enter a value...",
      },
      long: {
        id: "long",
        component: "TextField",
        variant: "longText",
        label: "Long text",
        placeholder: "Enter a longer description...",
      },
      num: {
        id: "num",
        component: "TextField",
        variant: "number",
        label: "Number",
        placeholder: "0",
      },
    },
  },
  {
    title: "CheckBox",
    category: "Interactive",
    description: "Checkbox with label text.",
    components: {
      root: {
        id: "root",
        component: "Column",
        children: ["cb1", "cb2"],
      },
      cb1: { id: "cb1", component: "CheckBox", label: "Enable notifications", value: true },
      cb2: { id: "cb2", component: "CheckBox", label: "Accept terms", value: false },
    },
  },
  {
    title: "ChoicePicker",
    category: "Interactive",
    description: "Radio/checkbox group with optional chip display style.",
    components: {
      root: {
        id: "root",
        component: "Column",
        children: ["radio", "chips"],
      },
      radio: {
        id: "radio",
        component: "ChoicePicker",
        label: "Select size",
        variant: "singleSelection",
        options: [
          { label: "Small", value: "sm" },
          { label: "Medium", value: "md" },
          { label: "Large", value: "lg" },
        ],
      },
      chips: {
        id: "chips",
        component: "ChoicePicker",
        label: "Tags",
        variant: "multipleSelection",
        displayStyle: "chips",
        options: [
          { label: "Design", value: "design" },
          { label: "Engineering", value: "eng" },
          { label: "Marketing", value: "mkt" },
        ],
      },
    },
  },
  {
    title: "Slider",
    category: "Interactive",
    description: "Range slider with min/max bounds.",
    components: {
      root: {
        id: "root",
        component: "Slider",
        label: "Temperature",
        min: 0,
        max: 100,
        value: 50,
      },
    },
  },
  {
    title: "DateTimeInput",
    category: "Interactive",
    description: "Date, time, or datetime picker.",
    components: {
      root: {
        id: "root",
        component: "Column",
        children: ["date", "time"],
      },
      date: {
        id: "date",
        component: "DateTimeInput",
        label: "Select date",
        enableDate: true,
        enableTime: false,
      },
      time: {
        id: "time",
        component: "DateTimeInput",
        label: "Select time",
        enableDate: false,
        enableTime: true,
      },
    },
  },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

const CATEGORY_ORDER: CatalogEntry["category"][] = [
  "Display",
  "Layout",
  "Container",
  "Interactive",
];

const CATEGORY_COLORS: Record<string, string> = {
  Display: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  Layout: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
  Container: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  Interactive: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
};

function buildSurfaceData(entry: CatalogEntry, index: number): A2UISurfaceData {
  return {
    id: `catalog-${index}`,
    timestamp: new Date().toISOString(),
    agent_id: "",
    event_type: "a2ui_surface",
    surfaceId: `catalog-surface-${index}`,
    surface: {
      surfaceId: `catalog-surface-${index}`,
      catalogId: "https://a2ui.org/specification/v0_9/basic_catalog.json",
      components: entry.components,
      dataModel: entry.dataModel ?? {},
    },
  };
}

// ── Catalog component ────────────────────────────────────────────────────────

export function A2UICatalog({ agentId }: { agentId: string }) {
  const grouped = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    entries: CATALOG.filter((e) => e.category === cat),
  }));

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-semibold text-foreground">
          A2UI Component Catalog
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          18 primitives from the{" "}
          <span className="font-mono text-xs">v0.9 basic catalog</span>.
          Agents can compose these components to build dynamic UI surfaces during task execution.
        </p>
      </div>

      {grouped.map(({ category, entries }) => (
        <div key={category} className="space-y-4">
          <div className="flex items-center gap-2">
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${CATEGORY_COLORS[category]}`}
            >
              {category}
            </span>
            <span className="text-xs text-muted-foreground">
              {entries.length} component{entries.length !== 1 ? "s" : ""}
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {entries.map((entry, i) => {
              const globalIdx = CATALOG.indexOf(entry);
              return (
                <div
                  key={entry.title}
                  className="flex flex-col rounded-lg border border-border bg-card"
                >
                  <div className="border-b border-border px-4 py-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-semibold text-foreground font-mono">
                        {entry.title}
                      </h3>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {entry.description}
                    </p>
                  </div>
                  <div className="flex-1 p-4">
                    <A2UIMessage data={buildSurfaceData(entry, globalIdx)} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
