import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Slim Docker runtime image (.next/standalone + server.js).
  output: "standalone",
  async redirects() {
    return [
      // Anonymous users land on the auth screen.
      { source: "/", destination: "/auth", permanent: false },
      // Builder Studio was folded into the AI Compiler; its listing lives in Projects.
      { source: "/user/builder", destination: "/user/projects", permanent: false },
    ];
  },
};

export default nextConfig;