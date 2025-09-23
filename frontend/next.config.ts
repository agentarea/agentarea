import type { NextConfig } from "next";
import createNextIntlPlugin from 'next-intl/plugin';

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
  env: {
    NEXT_PUBLIC_ORY_SDK_URL: process.env.NEXT_PUBLIC_ORY_SDK_URL || 'http://localhost:4433',
    ORY_ADMIN_URL: process.env.ORY_ADMIN_URL || 'http://localhost:4434',
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  },
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
