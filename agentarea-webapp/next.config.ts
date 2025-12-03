import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import "./src/env";

const nextConfig: NextConfig = {
  /* config options here */
  eslint: {
    // Do not fail the build on ESLint warnings; errors are handled via lint script
    ignoreDuringBuilds: true,
  },
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
  transpilePackages: ["@t3-oss/env-nextjs", "@t3-oss/env-core"],
};

const withNextIntl = createNextIntlPlugin();
export default withNextIntl(nextConfig);
