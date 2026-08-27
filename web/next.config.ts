import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Slim Docker runtime image (.next/standalone + server.js).
  output: "standalone",
  async redirects() {
    return [
      // Anonymous users land on the auth screen.
      { source: "/", destination: "/auth", permanent: false },
    ];
  },
};

export default nextConfig;