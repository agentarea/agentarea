// Ambient declaration for `*.svg` imports.
//
// The vendored `@ory/elements-react` package exposes its TYPES from source
// (`exports.types -> ./src/...`), so `tsc` type-checks its `.tsx` files, which
// `import Icon from "./x.svg"`. That package's own `declare module "*.svg"`
// lives under `packages/`, which this project's tsconfig excludes, so the
// ambient declaration is never loaded and the imports fail with TS2307.
//
// The webapp itself does not import `.svg` files, so declaring the module here
// (matching elements-react's `SVGIcon` shape) is safe and resolves the imports
// during type-check without pulling the excluded `packages/` tree back in.
declare module "*.svg" {
  import type { ComponentProps, FunctionComponent } from "react";

  const ReactComponent: FunctionComponent<
    ComponentProps<"svg"> & { size?: number }
  >;
  export default ReactComponent;
}
