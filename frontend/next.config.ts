import type { NextConfig } from "next";
import createNextIntlPlugin from 'next-intl/plugin';
import "./src/env";

const nextConfig: NextConfig = {
  /* config options here */
  eslint: {
    // Do not fail the build on ESLint warnings; errors are handled via lint script
    ignoreDuringBuilds: true,
  },
  images: {
    domains: [
      "api.dicebear.com",
      "cdn-icons-png.flaticon.com",
      "github.githubassets.com",
      "cdn.worldvectorlogo.com",
      "upload.wikimedia.org",
      "encrypted-tbn0.gstatic.com"
    ],
  },
  output: "standalone",
  async rewrites() {
    const backendUrl = process.env.API_URL || 'http://localhost:8000';
    const kratosUrl = process.env.ORY_ADMIN_URL?.replace(':4434', ':4433') || 'http://localhost:4433';

    return [
      {
        source: '/self-service/:path*',
        destination: `${kratosUrl}/self-service/:path*`,
      },
      {
        source: '/sessions/:path*',
        destination: `${kratosUrl}/sessions/:path*`,
      },
      {
        source: '/api/static/:path*',
        destination: `${backendUrl}/static/:path*`,
      },
    ];
  },
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      '@/ory.config': './ory.config.ts',
    };
    return config;
  },
};

const withNextIntl = createNextIntlPlugin();
export default withNextIntl(nextConfig);
