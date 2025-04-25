import type { NextConfig } from "next";
import createNextIntlPlugin from 'next-intl/plugin';

const nextConfig: NextConfig = {
  /* config options here */
  // images: {
  //   domains: ["api.dicebear.com"],
  // },
  output: "standalone",
};

const withNextIntl = createNextIntlPlugin();
export default withNextIntl(nextConfig);
