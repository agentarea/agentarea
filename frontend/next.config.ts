import type { NextConfig } from "next";
import createNextIntlPlugin from 'next-intl/plugin';
import "./src/env";

const nextConfig: NextConfig = {
  /* config options here */
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
    return [
      {
        source: '/self-service/:path*',
        destination: 'http://localhost:4433/self-service/:path*',
      },
      {
        source: '/sessions/:path*',
        destination: 'http://localhost:4433/sessions/:path*',
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
