# ---------------------------------------------------------------------------
# EnterpriseAI Web (Next.js) — build context is ./web
#   docker build -t enterpriseai-web ./web
#
# NEXT_PUBLIC_* vars are inlined at BUILD time; pass --build-arg to override.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS base
RUN npm install -g pnpm@11.24.0
WORKDIR /app

# --- Dependencies (cached layer) -------------------------------------------
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# Approve esbuild/sharp postinstall scripts explicitly (pnpm 11 requires it).
RUN pnpm install --frozen-lockfile --dangerously-allow-all-builds

# --- Build -------------------------------------------------------------------
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN pnpm build

# --- Runtime (slim, standalone server) ---------------------------------------
FROM node:22-alpine AS runner
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

CMD ["node", "server.js"]