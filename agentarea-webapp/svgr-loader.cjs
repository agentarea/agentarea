// Custom webpack loader: converts SVG files to React components
// using @svgr/core + @babel/core (both already available as transitive deps)
// This replaces the esbuild-plugin-svgr that tsup used during the pre-build step.

const { transform } = require("@svgr/core")
const svgo = require("@svgr/plugin-svgo")
const jsx = require("@svgr/plugin-jsx")
const babel = require("@babel/core")
const path = require("path")

// Resolve the preset using an absolute path because pnpm's virtual store
// prevents Babel from finding it by name when required from a non-standard location.
const presetReact = require("@babel/preset-react")

module.exports = async function svgrLoader(source) {
  const callback = this.async()

  // Derive a PascalCase component name from the SVG filename
  const filename = path.basename(this.resourcePath, ".svg")
  const componentName =
    filename
      .split(/[-_]/)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join("") + "Icon"

  try {
    // Step 1: Convert SVG to JSX using @svgr/core with the same options
    // that tsup.config.ts used via esbuild-plugin-svgr
    const jsxCode = await transform(
      source,
      {
        plugins: [svgo, jsx],
        jsxRuntime: "automatic",
        svgProps: {
          width: "{props?.width ? props.width : props?.size ?? 20}",
          height: "{props?.height ? props.height : props?.size ?? 20}",
        },
      },
      { componentName },
    )

    // Step 2: Convert JSX to plain JS so webpack can process it without
    // needing a separate JSX transform loader in the chain.
    // Use the resolved preset reference to avoid pnpm resolution issues.
    const result = babel.transformSync(jsxCode, {
      presets: [[presetReact, { runtime: "automatic" }]],
      configFile: false,
      babelrc: false,
    })

    callback(null, result.code)
  } catch (err) {
    callback(err)
  }
}
