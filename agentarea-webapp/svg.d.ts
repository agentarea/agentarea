// Ambient declaration for `*.svg` imports.
//
// The vendored `@ory/elements-react` package exposes its TYPES from source
// (`exports.types -> ./src/...`), so `tsc` type-checks its `.tsx` files, which
// `import Icon from "./x.svg"`. That package's own `declare module "*.svg"`
// lives under `packages/`, which this project's tsconfig excludes, so the
// ambient declaration is never loaded and the imports fail with TS2307.
//
// The webapp itself does not import `.svg` files, so declaring the module here
// is safe. The type is intentionally loose (`any`): elements-react uses these
// imports both as components (`<Icon />`) and, in a couple of files, unwrapped
// via `.default`. A precise component type makes `typeof x === "object"`
// narrow to `never` under strict TS, breaking the `.default` path
// (settings-oidc.tsx), so `any` mirrors the loose typing the package assumes.
declare module "*.svg" {
  const content: any;
  export default content;
}
