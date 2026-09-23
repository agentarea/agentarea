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
import { useA2UIDataModel } from "../hooks/useA2UIDataModel";
import { A2UIAction, A2UIComponent, A2UISurfaceData } from "../types";
import {
  buildButtonAction,
  resolvePointer,
  selectedChoices,
  toggleChoice,
} from "../utils/a2uiForm";

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
  disabled?: boolean;
  onValueChange: (path: string, value: unknown) => void;
  onAction?: (
    action: A2UIAction,
    sourceComponentId: string,
    context: Record<string, unknown>
  ) => void;
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

const A2UIInput: React.FC<{ node: A2UIComponent; ctx: RenderCtx }> = ({
  node,
  ctx,
}) => {
  const id = React.useId();
  const [local, setLocal] = React.useState({
    source: node.value,
    value: node.value as unknown,
  });
  if (local.source !== node.value)
    setLocal({ source: node.value, value: node.value });
  const binding =
    node.value && typeof node.value === "object" && "path" in node.value
      ? node.value.path
      : null;
  const value =
    binding !== null ? resolvePointer(ctx.dataModel, binding) : local.value;
  const update = (next: unknown) => {
    if (binding !== null) ctx.onValueChange(binding, next);
    else setLocal({ source: node.value, value: next });
  };
  const label = resolveString(node.label, ctx.dataModel);
  const textValue =
    typeof value === "string" || typeof value === "number" ? value : "";
  const inputClass =
    "w-full rounded-md border border-border bg-background px-3 py-1.5 text-[13px] leading-5 text-foreground";

  if (node.component === "CheckBox") {
    return (
      <label className="flex items-center gap-2 text-[13px] leading-5 text-foreground">
        <input
          type="checkbox"
          checked={value === true}
          onChange={(event) => update(event.target.checked)}
        />
        {label}
      </label>
    );
  }
  if (node.component === "ChoicePicker") {
    const selected = selectedChoices(value);
    const multiple = node.variant === "multipleSelection";
    const choose = (option: string) =>
      update(toggleChoice(selected, option, multiple));
    return (
      <fieldset className="flex flex-col gap-1">
        {label && (
          <legend className="text-[13px] font-medium leading-5">{label}</legend>
        )}
        <div
          className={
            node.displayStyle === "chips"
              ? "flex flex-wrap gap-2"
              : "flex flex-col gap-1"
          }
        >
          {(node.options ?? []).map((option) =>
            node.displayStyle === "chips" ? (
              <button
                key={option.value}
                type="button"
                aria-pressed={selected.includes(option.value)}
                className="rounded-full border border-border px-2.5 py-0.5 text-[13px] aria-pressed:bg-muted"
                onClick={() => choose(option.value)}
              >
                {option.label}
              </button>
            ) : (
              <label
                key={option.value}
                className="flex items-center gap-2 text-[13px] leading-5"
              >
                <input
                  type={multiple ? "checkbox" : "radio"}
                  name={id}
                  value={option.value}
                  checked={selected.includes(option.value)}
                  onChange={() => choose(option.value)}
                />
                {option.label}
              </label>
            )
          )}
        </div>
      </fieldset>
    );
  }
  const secret = node.component === "TextField" && node.variant === "obscured";
  const type =
    node.component === "Slider"
      ? "range"
      : node.component === "DateTimeInput"
        ? node.enableDate && node.enableTime
          ? "datetime-local"
          : node.enableDate
            ? "date"
            : "time"
        : node.variant === "number"
          ? "number"
          : secret
            ? "password"
            : "text";
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label
          htmlFor={id}
          className="text-[13px] font-medium leading-5 text-foreground"
        >
          {label}
        </label>
      )}
      {node.component === "TextField" && node.variant === "longText" ? (
        <textarea
          id={id}
          className={inputClass}
          rows={4}
          value={textValue}
          placeholder={resolveString(node.placeholder, ctx.dataModel)}
          onChange={(event) => update(event.target.value)}
        />
      ) : (
        <input
          id={id}
          type={type}
          className={inputClass}
          disabled={secret || node.disabled}
          value={secret ? "" : textValue}
          min={resolveInputValue(node.min, ctx.dataModel)}
          max={resolveInputValue(node.max, ctx.dataModel)}
          placeholder={resolveString(node.placeholder, ctx.dataModel)}
          onChange={(event) =>
            update(
              type === "number" || type === "range"
                ? event.target.value === ""
                  ? ""
                  : event.target.valueAsNumber
                : event.target.value
            )
          }
        />
      )}
      {secret && (
        <p className="text-xs text-muted-foreground">
          Use the secure input form to submit secrets.
        </p>
      )}
    </div>
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
      const cls =
        variantClass[node.variant ?? "body"] ?? "text-[13px] leading-5";
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
        const send = buildButtonAction({
          action: node.action,
          dataModel: dm,
          disabled: ctx.disabled,
        });
        if (send && ctx.onAction)
          ctx.onAction(send.action, node.id, send.context);
      };
      return (
        <button
          className={`cursor-pointer rounded-md px-3 py-1.5 text-[13px] font-medium leading-5 ${variantClass[node.variant ?? "default"] ?? variantClass.default}`}
          disabled={node.disabled || ctx.disabled}
          title={resolveString(node.accessibility?.label, dm)}
          onClick={handleClick}
        >
          {child ? renderById(child, ctx, depth + 1, visited) : null}
        </button>
      );
    }

    case "TextField":
    case "CheckBox":
    case "ChoicePicker":
    case "Slider":
    case "DateTimeInput":
      return <A2UIInput node={node} ctx={ctx} />;

    default:
      return null;
  }
};

// ── Surface renderer ──────────────────────────────────────────────────────────

const A2UIMessage: React.FC<{
  data: A2UISurfaceData;
  disabled?: boolean;
  onAction?: (
    action: A2UIAction,
    sourceComponentId: string,
    context: Record<string, unknown>
  ) => void;
}> = ({ data, onAction, disabled }) => {
  const { surface } = data;
  const [dataModel, setValue] = useA2UIDataModel(surface.dataModel);
  const ctx: RenderCtx = {
    components: surface.components,
    dataModel,
    surfaceId: surface.surfaceId,
    disabled,
    onValueChange: setValue,
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
    <fieldset disabled={disabled} className="a2ui-surface min-w-0 py-1">
      <A2UINode node={rootNode} ctx={ctx} />
    </fieldset>
  );
};

export default A2UIMessage;
