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
};

const withNextIntl = createNextIntlPlugin();
export default withNextIntl(nextConfig);
