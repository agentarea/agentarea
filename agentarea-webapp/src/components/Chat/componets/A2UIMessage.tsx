/**
 * A2UIMessage — renders an A2UI v0.9 surface.
 *
 * Protocol: https://a2ui.org/specification/v0.9-a2ui/
 * Components are stored as a flat adjacency-list (id → node).
 * Children are referenced by ID, not nested.
 * DynamicString values are resolved against the surface data model.
 */
import React from "react";
import { A2UIComponent, A2UISurfaceData } from "../types";

// ── DynamicString resolution ──────────────────────────────────────────────────

type DynamicString = string | { path: string } | null | undefined;

function resolveString(
  value: DynamicString,
  dataModel: Record<string, any>
): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  // JSON Pointer (RFC 6901) lookup
  return resolvePointer(dataModel, value.path) ?? "";
}

function resolvePointer(obj: any, pointer: string): any {
  const parts = (pointer || "/")
    .replace(/^\//, "")
    .split("/")
    .map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
  return parts.reduce((cur, key) => (cur != null ? cur[key] : undefined), obj);
}

// ── Component renderer ────────────────────────────────────────────────────────

interface RenderCtx {
  components: Record<string, A2UIComponent>;
  dataModel: Record<string, any>;
}

function renderById(id: string, ctx: RenderCtx): React.ReactNode {
  const node = ctx.components[id];
  if (!node) return null;
  return <A2UINode key={id} node={node} ctx={ctx} />;
}

function renderChildren(ids: string[] | undefined, ctx: RenderCtx): React.ReactNode[] {
  return (ids ?? []).map((id) => renderById(id, ctx));
}

const A2UINode: React.FC<{ node: A2UIComponent; ctx: RenderCtx }> = ({
  node,
  ctx,
}) => {
  const { component: type, child, children } = node;
  const dm = ctx.dataModel;

  switch (type) {
    // ── Display ──────────────────────────────────────────────────────────────

    case "Text": {
      const variantClass: Record<string, string> = {
        h1: "text-2xl font-bold",
        h2: "text-xl font-bold",
        h3: "text-lg font-semibold",
        h4: "text-base font-semibold",
        h5: "text-sm font-semibold",
        caption: "text-xs text-gray-500",
        body: "text-sm",
      };
      const cls = variantClass[node.variant ?? "body"] ?? "text-sm";
      return (
        <span className={`${cls} text-gray-800 dark:text-gray-200`}>
          {resolveString(node.text, dm)}
        </span>
      );
    }

    case "Image":
      return (
        <img
          src={resolveString(node.url, dm)}
          alt={resolveString(node.alt, dm) || ""}
          className="max-w-full rounded-md"
          style={{ objectFit: node.fit ?? "contain" }}
        />
      );

    case "Icon":
      // Render as text placeholder; real impl would use an icon library
      return (
        <span
          className="inline-block text-gray-600 dark:text-gray-400"
          aria-label={resolveString(node.name, dm)}
          title={resolveString(node.name, dm)}
        >
          [{resolveString(node.name, dm)}]
        </span>
      );

    case "Video":
      return (
        <video
          src={resolveString(node.url, dm)}
          controls
          className="max-w-full rounded-md"
        />
      );

    case "AudioPlayer":
      return (
        <div className="flex flex-col gap-1">
          {node.description && (
            <span className="text-xs text-gray-500">
              {resolveString(node.description, dm)}
            </span>
          )}
          <audio src={resolveString(node.url, dm)} controls className="w-full" />
        </div>
      );

    case "Divider":
      return node.axis === "vertical" ? (
        <div className="w-px self-stretch bg-gray-200 dark:bg-gray-700" />
      ) : (
        <hr className="border-gray-200 dark:border-gray-700" />
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
          className={`flex flex-row flex-wrap gap-2 ${justifyClass[node.justify ?? "start"] ?? ""} ${alignClass[node.align ?? "stretch"] ?? ""}`}
        >
          {renderChildren(children, ctx)}
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
          className={`flex flex-col gap-2 ${justifyClass[node.justify ?? "start"] ?? ""} ${alignClass[node.align ?? "stretch"] ?? ""}`}
        >
          {renderChildren(children, ctx)}
        </div>
      );
    }

    case "List":
      return (
        <ul
          className={`flex gap-1 ${node.direction === "horizontal" ? "flex-row flex-wrap" : "flex-col"}`}
        >
          {renderChildren(children, ctx)}
        </ul>
      );

    // ── Container ────────────────────────────────────────────────────────────

    case "Card":
      return (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
          {child ? renderById(child, ctx) : null}
        </div>
      );

    case "Tabs": {
      const tabs: Array<{ title: string; child: string }> = node.tabs ?? [];
      const [active, setActive] = React.useState(0);
      return (
        <div className="flex flex-col gap-2">
          <div className="flex gap-1 border-b border-gray-200 dark:border-gray-700">
            {tabs.map((tab, i) => (
              <button
                key={i}
                onClick={() => setActive(i)}
                className={`px-3 py-1.5 text-sm font-medium ${
                  active === i
                    ? "border-b-2 border-blue-600 text-blue-600"
                    : "text-gray-600 hover:text-gray-900 dark:text-gray-400"
                }`}
              >
                {tab.title}
              </button>
            ))}
          </div>
          <div>{tabs[active] ? renderById(tabs[active].child, ctx) : null}</div>
        </div>
      );
    }

    case "Modal": {
      const [open, setOpen] = React.useState(false);
      return (
        <>
          <div onClick={() => setOpen(true)} className="cursor-pointer">
            {node.trigger ? renderById(node.trigger, ctx) : null}
          </div>
          {open && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
              <div className="relative max-h-[80vh] w-full max-w-md overflow-auto rounded-xl bg-white p-6 shadow-xl dark:bg-gray-800">
                <button
                  onClick={() => setOpen(false)}
                  className="absolute right-3 top-3 text-gray-400 hover:text-gray-600"
                >
                  ✕
                </button>
                {node.content ? renderById(node.content, ctx) : null}
              </div>
            </div>
          )}
        </>
      );
    }

    // ── Interactive ──────────────────────────────────────────────────────────

    case "Button": {
      const variantClass: Record<string, string> = {
        default: "bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-200",
        primary: "bg-blue-600 text-white hover:bg-blue-700",
        borderless: "text-blue-600 hover:underline",
      };
      return (
        <button
          className={`rounded-md px-3 py-1.5 text-sm font-medium ${variantClass[node.variant ?? "default"] ?? variantClass.default}`}
          disabled={node.disabled}
          title={resolveString(node.accessibility?.label, dm)}
        >
          {child ? renderById(child, ctx) : null}
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
            <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
              {resolveString(node.label, dm)}
            </label>
          )}
          {isLong ? (
            <textarea
              className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200"
              placeholder={resolveString(node.placeholder, dm)}
              defaultValue={resolveString(node.value, dm)}
              rows={4}
              readOnly
            />
          ) : (
            <input
              type={inputType}
              className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200"
              placeholder={resolveString(node.placeholder, dm)}
              defaultValue={resolveString(node.value, dm)}
              readOnly
            />
          )}
        </div>
      );
    }

    case "CheckBox":
      return (
        <label className="flex items-center gap-2 text-sm text-gray-800 dark:text-gray-200">
          <input
            type="checkbox"
            defaultChecked={!!node.value}
            readOnly
            className="rounded"
          />
          {resolveString(node.label, dm)}
        </label>
      );

    case "ChoicePicker": {
      const options: Array<{ label: string; value: string }> = node.options ?? [];
      const isMulti = node.variant === "multipleSelection";
      const useChips = node.displayStyle === "chips";

      if (useChips) {
        return (
          <div className="flex flex-wrap gap-2">
            {options.map((opt) => (
              <span
                key={opt.value}
                className="cursor-pointer rounded-full border border-gray-300 px-3 py-0.5 text-sm text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300"
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
            <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
              {resolveString(node.label, dm)}
            </label>
          )}
          {options.map((opt) => (
            <label
              key={opt.value}
              className="flex items-center gap-2 text-sm text-gray-800 dark:text-gray-200"
            >
              <input type={isMulti ? "checkbox" : "radio"} value={opt.value} readOnly />
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
            <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
              {resolveString(node.label, dm)}
            </label>
          )}
          <input
            type="range"
            min={node.min ?? 0}
            max={node.max}
            defaultValue={typeof node.value === "number" ? node.value : 0}
            readOnly
            className="w-full"
          />
        </div>
      );

    case "DateTimeInput":
      return (
        <div className="flex flex-col gap-1">
          {node.label && (
            <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
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
            defaultValue={resolveString(node.value, dm)}
            min={node.min}
            max={node.max}
            readOnly
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200"
          />
        </div>
      );

    default:
      return null;
  }
};

// ── Surface renderer ──────────────────────────────────────────────────────────

const A2UIMessage: React.FC<{ data: A2UISurfaceData }> = ({ data }) => {
  const { surface } = data;
  const ctx: RenderCtx = {
    components: surface.components,
    dataModel: surface.dataModel,
  };

  const rootNode = surface.components["root"];
  if (!rootNode) {
    // Surface created but no components yet — show skeleton
    return (
      <div className="a2ui-surface flex items-center gap-2 rounded-xl bg-gray-50 p-4 text-sm text-gray-400 dark:bg-gray-800/50">
        <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-blue-400" />
        Rendering UI surface…
      </div>
    );
  }

  return (
    <div className="a2ui-surface rounded-xl bg-gray-50 p-4 dark:bg-gray-800/50">
      <A2UINode node={rootNode} ctx={ctx} />
    </div>
  );
};

export default A2UIMessage;
