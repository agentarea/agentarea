import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// Each HTML entry is built separately into one self-contained file: an MCP App
// view is delivered as the text of a single `ui://` resource, so it cannot load
// sibling script or style files.
const INPUT = process.env.INPUT;
if (!INPUT) {
  throw new Error("INPUT environment variable is not set");
}

export default defineConfig({
  plugins: [viteSingleFile()],
  build: {
    outDir: "dist",
    emptyOutDir: false,
    rollupOptions: { input: INPUT },
  },
});
