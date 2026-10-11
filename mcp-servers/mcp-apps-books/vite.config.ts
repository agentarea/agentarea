import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import pkg from "./package.json" with { type: "json" };

// Each HTML entry is built separately into one self-contained file: an MCP App
// view is delivered as the text of a single `ui://` resource, so it cannot load
// sibling script, style, or font files.
const INPUT = process.env.INPUT;
if (!INPUT) {
  throw new Error("INPUT environment variable is not set");
}

export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "app"),
      "@shared": path.resolve(import.meta.dirname, "shared"),
      "@kit": path.resolve(import.meta.dirname, "../mcp-apps-kit"),
    },
    // The kit lives outside this package and has no node_modules: its imports resolve from here.
    dedupe: Object.keys(pkg.dependencies),
  },
  build: {
    outDir: "dist",
    emptyOutDir: false,
    rollupOptions: { input: INPUT },
  },
});
