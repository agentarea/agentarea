/**
 * A2UIMessage — renders an A2UI v0.9 surface.
 *
 * Protocol: https://a2ui.org/specification/v0.9-a2ui/
 * Components are stored as a flat adjacency-list (id → node).
 * Children are referenced by ID, not nested.
 * DynamicString values are resolved against the surface data model.
 */
import React from "react";
import Image from "next/image";
import { A2UIAction, A2UIComponent, A2UISurfaceData } from "../types";

// ── DynamicString resolution ──────────────────────────────────────────────────

type DynamicString = string | { path: string } | null | undefined;
type DynamicInputValue =
  | string
  | number
  | boolean
  | { path: string }
  | null
  | undefined;

function resolveString(
  value: DynamicString,
  dataModel: Record<string, unknown>
): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  // JSON Pointer (RFC 6901) lookup
  return (resolvePointer(dataModel, value.path) ?? "") as string;
}

function resolveInputValue(
  value: DynamicInputValue,
  dataModel: Record<string, unknown>
): string | number | undefined {
  if (value == null) return undefined;
  if (typeof value === "string" || typeof value === "number") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  const resolved = resolvePointer(dataModel, value.path);
  return typeof resolved === "string" || typeof resolved === "number"
    ? resolved
    : undefined;
}

function resolvePointer(obj: unknown, pointer: string): unknown {
  const parts = (pointer || "/")
    .replace(/^\//, "")
    .split("/")
    .map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
  return parts.reduce(
    (cur: unknown, key): unknown =>
      cur != null && typeof cur === "object"
        ? (cur as Record<string, unknown>)[key]
        : undefined,
    obj
  );
}

// ── URL sanitization ─────────────────────────────────────────────────────────

function sanitizeMediaUrl(url: string): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    if (!["https:", "http:", "data:"].includes(parsed.protocol)) return "";
    return parsed.href;
  } catch {
    return "";
  }
}

// ── Component renderer ────────────────────────────────────────────────────────

const MAX_RENDER_DEPTH = 50;

interface RenderCtx {
  components: Record<string, A2UIComponent>;
  dataModel: Record<string, unknown>;
  surfaceId: string;
  onAction?: (action: A2UIAction, sourceComponentId: string) => void;
}

function renderById(
  id: string,
  ctx: RenderCtx,
  depth = 0,
  visited = new Set<string>()
): React.ReactNode {
  if (depth > MAX_RENDER_DEPTH || visited.has(id)) return null;
  const node = ctx.components[id];
  if (!node) return null;
  const next = new Set(visited);
  next.add(id);
  return (
    <A2UINode key={id} node={node} ctx={ctx} depth={depth} visited={next} />
  );
}

function renderChildren(
  ids: string[] | undefined,
  ctx: RenderCtx,
  depth = 0,
  visited = new Set<string>()
): React.ReactNode[] {
  return (ids ?? []).map((id) => renderById(id, ctx, depth, visited));
}

const A2UITabs: React.FC<{
  node: A2UIComponent;
  ctx: RenderCtx;
  depth?: number;
  visited?: Set<string>;
}> = ({ node, ctx, depth = 0, visited = new Set() }) => {
  const tabs: Array<{ title: string; child: string }> = node.tabs ?? [];
  const [active, setActive] = React.useState(0);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1 border-b border-border">
        {tabs.map((tab, i) => (
          <button
            key={i}
            onClick={() => setActive(i)}
            className={`px-2.5 py-1.5 text-[13px] font-medium leading-5 ${
              active === i
                ? "border-b-2 border-foreground text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.title}
          </button>
        ))}
      </div>
      <div>
        {tabs[active]
          ? renderById(tabs[active].child, ctx, depth + 1, visited)
          : null}
      </div>
    </div>
  );
};

const A2UIModal: React.FC<{
  node: A2UIComponent;
  ctx: RenderCtx;
  depth?: number;
  visited?: Set<string>;
}> = ({ node, ctx, depth = 0, visited = new Set() }) => {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <div onClick={() => setOpen(true)} className="cursor-pointer">
        {node.trigger
          ? renderById(node.trigger, ctx, depth + 1, visited)
          : null}
      </div>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="relative max-h-[80vh] w-full max-w-md overflow-auto rounded-lg border border-border bg-background p-4 shadow-xl">
            <button
              onClick={() => setOpen(false)}
              className="absolute right-3 top-3 text-muted-foreground hover:text-foreground"
            >
              ✕
            </button>
            {node.content
              ? renderById(node.content, ctx, depth + 1, visited)
              : null}
          </div>
        </div>
      )}
    </>
  );
};

const A2UINode: React.FC<{
  node: A2UIComponent;
  ctx: RenderCtx;
  depth?: number;
  visited?: Set<string>;
}> = ({ node, ctx, depth = 0, visited = new Set() }) => {
  const { component: type, child, children } = node;
  const dm = ctx.dataModel;

  switch (type) {
    // ── Display ──────────────────────────────────────────────────────────────

    case "Text": {
      const variantClass: Record<string, string> = {
        h1: "text-base font-semibold leading-6",
        h2: "text-[15px] font-semibold leading-6",
        h3: "text-sm font-semibold leading-5",
        h4: "text-[13px] font-semibold leading-5",
        h5: "text-[13px] font-medium leading-5",
        caption: "text-xs leading-5 text-muted-foreground",
        body: "text-[13px] leading-5",
      };
      const cls = variantClass[node.variant ?? "body"] ?? "text-[13px] leading-5";
      return (
        <span className={`${cls} text-foreground/85`}>
          {resolveString(node.text, dm)}
        </span>
      );
    }

    case "Image":
      return (
        <Image
          src={sanitizeMediaUrl(resolveString(node.url, dm))}
          alt={resolveString(node.alt, dm) || ""}
          width={800}
          height={600}
          className="max-w-full rounded-md"
          style={{ objectFit: node.fit ?? "contain" }}
        />
      );

    case "Icon":
      // Render as text placeholder; real impl would use an icon library
      return (
        <span
          className="inline-block text-muted-foreground"
          aria-label={resolveString(node.name, dm)}
          title={resolveString(node.name, dm)}
        >
          [{resolveString(node.name, dm)}]
        </span>
      );

    case "Video":
      return (
        <video
          src={sanitizeMediaUrl(resolveString(node.url, dm))}
          controls
          className="max-w-full rounded-md"
        />
      );

    case "AudioPlayer":
      return (
        <div className="flex flex-col gap-1">
          {node.description && (
            <span className="text-xs leading-5 text-muted-foreground">
              {resolveString(node.description, dm)}
            </span>
          )}
          <audio
            src={sanitizeMediaUrl(resolveString(node.url, dm))}
            controls
            className="w-full"
          />
        </div>
      );

    case "Divider":
      return node.axis === "vertical" ? (
        <div className="w-px self-stretch bg-border" />
      ) : (
        <hr className="border-border" />
      );

    // ── Layout ───────────────────────────────────────────────────────────────

    case "Row": {
      const justifyClass: Record<string, string> = {
        start: "justify-start",
        center: "justify-center",
        end: "justify-end",
        spaceBetween: "justify-between",
        spaceAround: "justify-around",
        spaceEvenly: "justify-evenly",
        stretch: "justify-stretch",
      };
      const alignClass: Record<string, string> = {
        start: "items-start",
        center: "items-center",
        end: "items-end",
        stretch: "items-stretch",
      };
      return (
        <div
          className={`flex flex-row flex-wrap gap-1.5 ${justifyClass[node.justify ?? "start"] ?? ""} ${alignClass[node.align ?? "stretch"] ?? ""}`}
        >
          {renderChildren(children, ctx, depth + 1, visited)}
        </div>
      );
    }

    case "Column": {
      const justifyClass: Record<string, string> = {
        start: "justify-start",
        center: "justify-center",
        end: "justify-end",
        spaceBetween: "justify-between",
        spaceAround: "justify-around",
        spaceEvenly: "justify-evenly",
        stretch: "justify-stretch",
      };
      const alignClass: Record<string, string> = {
        start: "items-start",
        center: "items-center",
        end: "items-end",
        stretch: "items-stretch",
      };
      return (
        <div
          className={`flex flex-col gap-1.5 ${justifyClass[node.justify ?? "start"] ?? ""} ${alignClass[node.align ?? "stretch"] ?? ""}`}
        >
          {renderChildren(children, ctx, depth + 1, visited)}
        </div>
      );
    }

    case "List":
      return (
        <ul
          className={`flex gap-1.5 ${node.direction === "horizontal" ? "flex-row flex-wrap" : "flex-col"}`}
        >
          {renderChildren(children, ctx, depth + 1, visited)}
        </ul>
      );

    // ── Container ────────────────────────────────────────────────────────────

    case "Card":
      return (
        <div className="border-l-2 border-border py-1 pl-3">
          {child ? renderById(child, ctx, depth + 1, visited) : null}
        </div>
      );

    case "Tabs":
      return (
        <A2UITabs node={node} ctx={ctx} depth={depth + 1} visited={visited} />
      );

    case "Modal":
      return (
        <A2UIModal node={node} ctx={ctx} depth={depth + 1} visited={visited} />
      );

    // ── Interactive ──────────────────────────────────────────────────────────

    case "Button": {
      const variantClass: Record<string, string> = {
        default:
          "border border-border bg-background text-foreground hover:bg-muted",
        primary: "bg-foreground text-background hover:bg-foreground/85",
        borderless: "text-foreground underline-offset-4 hover:underline",
      };
      const handleClick = () => {
        if (node.action && ctx.onAction) {
          ctx.onAction(node.action as A2UIAction, node.id);
        }
      };
      return (
        <button
          className={`cursor-pointer rounded-md px-3 py-1.5 text-[13px] font-medium leading-5 ${variantClass[node.variant ?? "default"] ?? variantClass.default}`}
          disabled={node.disabled}
          title={resolveString(node.accessibility?.label, dm)}
          onClick={handleClick}
        >
          {child ? renderById(child, ctx, depth + 1, visited) : null}
        </button>
      );
    }

    case "TextField": {
      const variantType: Record<string, string> = {
        shortText: "text",
        longText: "text",
        number: "number",
        obscured: "password",
      };
      const inputType = variantType[node.variant ?? "shortText"] ?? "text";
      const isLong = node.variant === "longText";
      return (
        <div className="flex flex-col gap-1">
          {node.label && (
            <label className="text-[13px] font-medium leading-5 text-foreground">
              {resolveString(node.label, dm)}
            </label>
          )}
          {isLong ? (
            <textarea
              className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-[13px] leading-5 text-foreground"
              placeholder={resolveString(node.placeholder, dm)}
              defaultValue={resolveInputValue(node.value, dm)}
              rows={4}
            />
          ) : (
            <input
              type={inputType}
              className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-[13px] leading-5 text-foreground"
              placeholder={resolveString(node.placeholder, dm)}
              defaultValue={resolveInputValue(node.value, dm)}
            />
          )}
        </div>
      );
    }

    case "CheckBox":
      return (
        <label className="flex items-center gap-2 text-[13px] leading-5 text-foreground">
          <input
            type="checkbox"
            defaultChecked={!!node.value}
            className="rounded"
          />
          {resolveString(node.label, dm)}
        </label>
      );

    case "ChoicePicker": {
      const options: Array<{ label: string; value: string }> =
        node.options ?? [];
      const isMulti = node.variant === "multipleSelection";
      const useChips = node.displayStyle === "chips";

      if (useChips) {
        return (
          <div className="flex flex-wrap gap-2">
            {options.map((opt) => (
              <span
                key={opt.value}
                className="cursor-pointer rounded-full border border-border px-2.5 py-0.5 text-[13px] leading-5 text-foreground hover:bg-muted"
              >
                {opt.label}
              </span>
            ))}
          </div>
        );
      }

      return (
        <div className="flex flex-col gap-1">
          {node.label && (
            <label className="text-[13px] font-medium leading-5 text-foreground">
              {resolveString(node.label, dm)}
            </label>
          )}
          {options.map((opt) => (
            <label
              key={opt.value}
              className="flex items-center gap-2 text-[13px] leading-5 text-foreground"
            >
              <input type={isMulti ? "checkbox" : "radio"} value={opt.value} />
              {opt.label}
            </label>
          ))}
        </div>
      );
    }

    case "Slider":
      return (
        <div className="flex flex-col gap-1">
          {node.label && (
            <label className="text-[13px] font-medium leading-5 text-foreground">
              {resolveString(node.label, dm)}
            </label>
          )}
          <input
            type="range"
            min={resolveInputValue(node.min, dm) ?? 0}
            max={resolveInputValue(node.max, dm)}
            defaultValue={typeof node.value === "number" ? node.value : 0}
            className="w-full"
          />
        </div>
      );

    case "DateTimeInput":
      return (
        <div className="flex flex-col gap-1">
          {node.label && (
            <label className="text-[13px] font-medium leading-5 text-foreground">
              {resolveString(node.label, dm)}
            </label>
          )}
          <input
            type={
              node.enableDate && node.enableTime
                ? "datetime-local"
                : node.enableDate
                  ? "date"
                  : "time"
            }
            defaultValue={resolveInputValue(node.value, dm)}
            min={resolveInputValue(node.min, dm)}
            max={resolveInputValue(node.max, dm)}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-[13px] leading-5 text-foreground"
          />
        </div>
      );

    default:
      return null;
  }
};

// ── Surface renderer ──────────────────────────────────────────────────────────

const A2UIMessage: React.FC<{
  data: A2UISurfaceData;
  onAction?: (action: A2UIAction, sourceComponentId: string) => void;
}> = ({ data, onAction }) => {
  const { surface } = data;
  const ctx: RenderCtx = {
    components: surface.components,
    dataModel: surface.dataModel,
    surfaceId: surface.surfaceId,
    onAction,
  };

  const rootNode = surface.components["root"];
  if (!rootNode) {
    // Surface created but no components yet — show skeleton
    return (
      <div className="a2ui-surface flex items-center gap-2 py-2 text-[13px] leading-5 text-muted-foreground">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-muted-foreground/60" />
        Rendering UI surface…
      </div>
    );
  }

  return (
    <div className="a2ui-surface min-w-0 py-1">
      <A2UINode node={rootNode} ctx={ctx} />
    </div>
  );
};

export default A2UIMessage;
