# ---------------------------------------------------------------------------
# EnterpriseAI Web (Next.js) — build context is ./web
#   docker build -t enterpriseai-web ./web
#
# NEXT_PUBLIC_* vars are inlined at BUILD time; pass --build-arg to override.
# ---------------------------------------------------------------------------
# Pinned so a moved tag never forces a full rebuild; bump deliberately:
#   docker pull node:22-alpine && docker image inspect --format '{{index .RepoDigests 0}}' node:22-alpine
ARG NODE_IMAGE=node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402

FROM ${NODE_IMAGE} AS base
RUN npm install -g pnpm@11.24.0
WORKDIR /app

# --- Dependencies (cached layer) -------------------------------------------
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# Approve esbuild/sharp postinstall scripts explicitly (pnpm 11 requires it).
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --dangerously-allow-all-builds

# --- Build -------------------------------------------------------------------
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1
# The backend (MCP catalog, knowledge bases, builder) — also browser-facing.
ARG NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8002/api/v1
# 1 = skip lint + type-check inside the image build (they roughly double
# `next build`); run them with `pnpm lint` / `pnpm exec tsc --noEmit`.
# --build-arg SKIP_BUILD_CHECKS=0 to keep them here too.
ARG SKIP_BUILD_CHECKS=1
# Build workers (see next.config.ts): few, so the build fits a small Docker VM.
ARG NEXT_BUILD_CPUS=2
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_BACKEND_API_URL=$NEXT_PUBLIC_BACKEND_API_URL \
    NEXT_TELEMETRY_DISABLED=1 \
    SKIP_BUILD_CHECKS=$SKIP_BUILD_CHECKS \
    NEXT_BUILD_CPUS=$NEXT_BUILD_CPUS

# Use BuildKit cache mount for Next.js build cache to speed up recompilation
RUN --mount=type=cache,target=/app/.next/cache \
    pnpm build

# --- Runtime (slim, standalone server) ---------------------------------------
FROM ${NODE_IMAGE} AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -S nodejs && adduser -S nextjs -G nodejs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["sh", "-c", "echo '==========================================================================' && echo '  🚀  EnterpriseAI Web:  http://localhost:'\"$PORT\" && echo '  🔐  Auth / Login UI:   http://localhost:'\"$PORT\"'/auth' && echo '==========================================================================' && exec node server.js"]