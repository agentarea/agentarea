import { applyDocumentTheme } from "@modelcontextprotocol/ext-apps";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

/** Starts one view: every view bundle is its own page with the same theming. */
export function mount(view: ReactNode) {
  // Until the host says otherwise, follow the viewer's OS setting.
  applyDocumentTheme(matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  createRoot(document.getElementById("root")!).render(<StrictMode>{view}</StrictMode>);
}
