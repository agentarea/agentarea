import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs/config";
import createNextIntlPlugin from "next-intl/plugin";
import packageJson from "./package.json";
import path from "path";
import { CONTENT_SECURITY_POLICY } from "./src/lib/csp";
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
    const backendUrl = process.env.AGENTAREA_API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/static/:path*",
        destination: `${backendUrl}/static/:path*`,
      },
    ];
  },
  async headers() {
    // Baseline security headers — see issue #483.
    return [
      {
        source: "/(.*)",
        headers: [{ key: "X-Content-Type-Options", value: "nosniff" }],
      },
      {
        // /app-sandbox is the MCP Apps frame, meant to be embedded by the
        // webapp; it sends its own CSP (frame-ancestors = the webapp origin).
        // This one, with frame-ancestors 'none', would replace it and the
        // browser would refuse to load the frame.
        source: "/((?!app-sandbox$).*)",
        headers: [
          { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
        ],
      },
    ];
  },
  env: {
    NEXT_PUBLIC_APP_VERSION:
      process.env.NEXT_PUBLIC_APP_VERSION ?? packageJson.version,
  },
  transpilePackages: ["@t3-oss/env-nextjs", "@t3-oss/env-core", "@ory/elements-react"],
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

    interface WebpackRule {
      oneOf?: WebpackRule[];
      test?: RegExp;
      exclude?: RegExp | RegExp[];
    }
    // Remove SVGs from the default static-asset rule so our loader takes over
    const rules = (config.module?.rules ?? []) as WebpackRule[];
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
export default withSentryConfig(withNextIntl(nextConfig), {
  silent: true,
  telemetry: false,
  sourcemaps: { disable: true },
  release: { create: false },
  suppressOnRouterTransitionStartWarning: true,
});
