import type { NextConfig } from "next";

// The Docker image build sets SKIP_BUILD_CHECKS=1: lint and type-check are
// the slowest part of `next build` and are run separately (`pnpm lint`,
// `pnpm exec tsc --noEmit`). A local `pnpm build` still runs both.
const skipChecks = process.env.SKIP_BUILD_CHECKS === "1";
// Worker processes for page-data collection / static generation. Next
// defaults to (CPUs - 1); a Docker VM often reports many CPUs but little
// memory, and a dozen workers each loading Next makes the build thrash.
const buildCpus = Number(process.env.NEXT_BUILD_CPUS) || undefined;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: skipChecks },
  typescript: { ignoreBuildErrors: skipChecks },
  ...(buildCpus ? { experimental: { cpus: buildCpus } } : {}),
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