import { applyDocumentTheme } from "@modelcontextprotocol/ext-apps";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

// Until the host says otherwise, follow the viewer's OS setting.
applyDocumentTheme(matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
