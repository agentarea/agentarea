import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import packageJson from "./package.json";
import path from "path";
import "./src/env";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" },
    ],
  },
  /* config options here */
  // eslint: {
  //   // Do not fail the build on ESLint warnings; errors are handled via lint script
  //   ignoreDuringBuilds: true,
  // },
  output: "standalone",
  async rewrites() {
    const backendUrl = process.env.API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/static/:path*",
        destination: `${backendUrl}/static/:path*`,
      },
    ];
  },
  async redirects() {
    // The MCP "Connections" feature now lives under /connections.
    // Keep old /mcp-servers bookmarks and deep links working.
    return [
      {
        source: "/mcp-servers",
        destination: "/connections",
        permanent: false,
      },
      {
        source: "/mcp-servers/:path*",
        destination: "/connections/:path*",
        permanent: false,
      },
    ];
  },
  env: {
    NEXT_PUBLIC_APP_VERSION:
      process.env.NEXT_PUBLIC_APP_VERSION ?? packageJson.version,
  },
  transpilePackages: ["@t3-oss/env-nextjs", "@t3-oss/env-core", "@ory/elements-react", "@ory/nextjs"],
  // Turbopack (used by default in next dev) needs its own SVG rule,
  // since it does not use the webpack() config below.
  turbopack: {
    rules: {
      "*.svg": {
        loaders: [{ loader: path.join(__dirname, "svgr-loader.cjs") }],
        as: "*.js",
      },
    },
  },
  webpack(config) {
    // When @ory/elements-react is transpiled directly (via transpilePackages),
    // its SVG imports need SVGR treatment to become React components.
    // Previously tsup + esbuild-plugin-svgr handled this; now webpack does it.

    // Remove SVGs from the default static-asset rule so our loader takes over
    const rules: any[] = config.module.rules;
    for (const rule of rules) {
      if (rule && typeof rule === "object" && rule.oneOf) {
        for (const oneOfRule of rule.oneOf) {
          if (
            oneOfRule.test instanceof RegExp &&
            oneOfRule.test.test(".svg")
          ) {
            oneOfRule.exclude = [
              ...(Array.isArray(oneOfRule.exclude) ? oneOfRule.exclude : oneOfRule.exclude ? [oneOfRule.exclude] : []),
              /\.svg$/i,
            ];
          }
        }
      }
      if (rule && typeof rule === "object" && !rule.oneOf && rule.test instanceof RegExp && rule.test.test(".svg")) {
        rule.exclude = [
          ...(Array.isArray(rule.exclude) ? rule.exclude : rule.exclude ? [rule.exclude] : []),
          /\.svg$/i,
        ];
      }
    }

    // Add SVGR-based loader: SVG → JSX → JS (React components)
    config.module.rules.push({
      test: /\.svg$/i,
      issuer: /\.[jt]sx?$/,
      use: [path.join(__dirname, "svgr-loader.cjs")],
    });

    return config;
  },
};

const withNextIntl = createNextIntlPlugin();
export default withNextIntl(nextConfig);
