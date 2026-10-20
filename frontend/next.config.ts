import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  experimental: {
    agentFeedback: true,
  },
  cacheComponents: true,
  partialPrefetching: true,
  // Same-origin path to a local Cognito emulator, which doesn't send CORS headers.
  async rewrites() {
    const target = process.env.COGNITO_DEV_PROXY_TARGET;
    if (!target) return [];
    return [
      { source: "/cognito", destination: `${target}/` },
      { source: "/cognito/:path*", destination: `${target}/:path*` },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
